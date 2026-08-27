from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pyphen
import soundfile as sf
import torch
import torchaudio

from f5_tts.infer.utils_infer import (
    convert_char_to_pinyin,
    load_checkpoint,
    load_model,
    preprocess_ref_audio_text,
    remove_silence_for_generated_wav,
)
from f5_tts.model import DiT

from .clf5_speed_predictor import SpeedPredictor
from .f5_pipeline import F5TTSPipeline


class CrossLingualF5TTSPipeline(F5TTSPipeline):
    TARGET_SAMPLE_RATE = 24000
    HOP_LENGTH = 256
    TARGET_RMS = 0.1
    MAX_TOTAL_SECONDS = 22.0

    def __init__(self, speaking_rate_ckpt_file: str, **kwargs):
        self.speaking_rate_ckpt_file = str(speaking_rate_ckpt_file)
        super().__init__(**kwargs)
        self.speaking_rate_model = self._load_speaking_rate_model()
        self._hyphenator = pyphen.Pyphen(lang="en_US")

    def _load_tts_model(self):
        model_cfg = {
            "dim": 1024,
            "depth": 22,
            "heads": 16,
            "ff_mult": 2,
            "text_dim": 512,
            "conv_layers": 4,
        }
        return load_model(
            DiT,
            model_cfg,
            self.config["ckpt_file"],
            mel_spec_type=self.config["vocoder_name"],
            vocab_file=self.config["vocab_file"],
            device=self.config["device"],
        )

    def _load_speaking_rate_model(self):
        model = SpeedPredictor(
            speed_type="syllables",
            mel_spec_kwargs={
                "target_sample_rate": self.TARGET_SAMPLE_RATE,
                "n_mel_channels": 100,
                "hop_length": self.HOP_LENGTH,
                "win_length": 1024,
                "n_fft": 1024,
                "mel_spec_type": "vocos",
            },
            arch_kwargs={"dim": 512, "depth": 6, "heads": 8, "ff_mult": 4},
        ).to(self.config["device"])
        return load_checkpoint(
            model,
            self.speaking_rate_ckpt_file,
            self.config["device"],
            dtype=torch.float32,
            use_ema=True,
        )

    def _count_units(self, text: str) -> int:
        units = 0.0
        for token in re.findall(r"[a-zA-Z']+|[\u4e00-\u9fff]", text):
            units += 1 if len(token) == 1 and "\u4e00" <= token <= "\u9fff" else len(
                self._hyphenator.inserted(token.lower()).split("-")
            )
        punctuation = {
            ".": 1.5, "!": 1.5, "?": 1.5, ",": 0.7, ";": 1.0, ":": 1.0,
            "。": 1.3, "！": 1.3, "？": 1.3, "，": 0.6, "；": 0.8, "：": 0.8,
        }
        units += sum(punctuation.get(char, 0.0) for char in text)
        return max(1, round(units))

    def _chunk_text(self, text: str, max_units: int) -> list[str]:
        chunks: list[str] = []
        current = ""
        sentences = re.split(r"(?<=[;:,.!?])\s+|(?<=[；：，。！？])", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip()
            if current and self._count_units(candidate) > max_units:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _prepare_audio(self, ref_audio: str):
        audio, sample_rate = torchaudio.load(ref_audio)
        if audio.shape[0] > 1:
            audio = torch.mean(audio, dim=0, keepdim=True)
        rms = torch.sqrt(torch.mean(torch.square(audio)))
        if rms < self.TARGET_RMS:
            audio = audio * self.TARGET_RMS / rms.clamp_min(1e-8)
        if sample_rate != self.TARGET_SAMPLE_RATE:
            audio = torchaudio.functional.resample(audio, sample_rate, self.TARGET_SAMPLE_RATE)
        return audio.to(self.config["device"]), rms

    def _predict_speed(self, audio: torch.Tensor) -> float:
        speed = float(self.speaking_rate_model.predict_speed(audio=audio).item())
        return max(speed, 0.25)

    def _decode_chunk(self, audio, rms, text, predicted_speed, run_config):
        speed = float(run_config["speed"])
        fix_duration = run_config.get("fix_duration")
        local_speed = 0.5 if self._count_units(text) < 4 else speed
        ref_audio_len = audio.shape[-1] // self.HOP_LENGTH
        if fix_duration is not None:
            duration = int(float(fix_duration) * self.TARGET_SAMPLE_RATE / self.HOP_LENGTH)
        else:
            generated_seconds = self._count_units(text) / predicted_speed / local_speed
            duration = ref_audio_len + int(generated_seconds * self.TARGET_SAMPLE_RATE / self.HOP_LENGTH)

        with torch.inference_mode():
            generated, _ = self.model.sample(
                cond=audio,
                text=convert_char_to_pinyin([text]),
                duration=duration,
                steps=int(run_config["nfe_step"]),
                cfg_strength=float(run_config["cfg_strength"]),
                sway_sampling_coef=float(run_config["sway_sampling_coef"]),
            )
            mel = generated.to(torch.float32)[:, ref_audio_len:, :].permute(0, 2, 1)
            wave = self.vocoder.decode(mel)
            if rms < self.TARGET_RMS:
                wave = wave * rms / self.TARGET_RMS
        return wave.squeeze().cpu().numpy(), mel[0].cpu().numpy()

    @staticmethod
    def _cross_fade(waves: list[np.ndarray], sample_rate: int, seconds: float) -> np.ndarray:
        final = waves[0]
        for next_wave in waves[1:]:
            samples = min(int(seconds * sample_rate), len(final), len(next_wave))
            if samples <= 0:
                final = np.concatenate((final, next_wave))
                continue
            fade_out = np.linspace(1.0, 0.0, samples)
            fade_in = np.linspace(0.0, 1.0, samples)
            overlap = final[-samples:] * fade_out + next_wave[:samples] * fade_in
            final = np.concatenate((final[:-samples], overlap, next_wave[samples:]))
        return final

    def generate(self, text_to_generate, output_path, **kwargs):
        run_config = self.config.copy()
        run_config.update(kwargs)

        if os.path.isfile(text_to_generate):
            gen_text = Path(text_to_generate).read_text(encoding="utf-8")
        else:
            gen_text = str(text_to_generate)
        if not gen_text.strip():
            return None

        ref_audio, _ = preprocess_ref_audio_text(run_config["ref_audio"], "Useless here.")
        audio, rms = self._prepare_audio(ref_audio)
        predicted_speed = self._predict_speed(audio)
        available_seconds = max(1.0, self.MAX_TOTAL_SECONDS - audio.shape[-1] / self.TARGET_SAMPLE_RATE)
        chunks = self._chunk_text(gen_text, max(1, int(predicted_speed * available_seconds)))

        torch.manual_seed(int(run_config["seed"]))
        waves: list[np.ndarray] = []
        for chunk in chunks:
            wave, _ = self._decode_chunk(
                audio,
                rms,
                chunk,
                predicted_speed,
                run_config,
            )
            waves.append(wave)

        if not waves:
            return None
        final_wave = self._cross_fade(
            waves,
            self.TARGET_SAMPLE_RATE,
            float(run_config["cross_fade_duration"]),
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, final_wave, self.TARGET_SAMPLE_RATE)
        if run_config.get("remove_silence"):
            remove_silence_for_generated_wav(str(output))
        return str(output.resolve())
