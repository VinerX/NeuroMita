import warnings
from typing import List, Optional, Tuple, Union, Sequence, Dict, Any

import hydra
import numpy as np
import omegaconf
import onnxruntime as rt
import torch

from .decoding import Tokenizer
from .preprocess import FeatureExtractor, load_audio

warnings.simplefilter("ignore", category=UserWarning)

DTYPE = np.float32
MAX_LETTERS_PER_FRAME = 3


def _np_i64(x: Union[int, Sequence[int]]) -> np.ndarray:
    return np.asarray(x, dtype=np.int64)


def _build_ort_inputs(
    sess: rt.InferenceSession,
    features: np.ndarray,
    feat_len: np.ndarray,
) -> Dict[str, Any]:
    """
    Универсально собирает inputs для encoder/ctc модели:
    - features: float32 [B, F, T]
    - feat_len: int64 [B]
    """
    ins = sess.get_inputs()
    if len(ins) != 2:
        raise RuntimeError(f"Expected 2 inputs, got {len(ins)}: {[i.name for i in ins]}")

    name0, name1 = ins[0].name, ins[1].name

    # Пытаемся понять где length по имени
    def is_len(n: str) -> bool:
        n = n.lower()
        return "length" in n or "len" == n or "feature_lengths" in n

    if is_len(name0) and not is_len(name1):
        return {name0: feat_len, name1: features}
    if is_len(name1) and not is_len(name0):
        return {name0: features, name1: feat_len}

    # fallback: как в исходном коде — первый features, второй length
    return {name0: features, name1: feat_len}


def _ctc_greedy_decode(log_probs: np.ndarray, tokenizer: Tokenizer) -> str:
    """
    log_probs: [B, T, C] (обычно B=1)
    blank_id = len(tokenizer)
    """
    if log_probs.ndim != 3:
        raise RuntimeError(f"CTC expected [B,T,C], got {log_probs.shape}")

    blank_id = len(tokenizer)
    labels = log_probs.argmax(axis=-1)  # [B, T]
    seq = labels[0].tolist()

    out: List[int] = []
    prev = blank_id
    for tok in seq:
        if tok != blank_id and (tok != prev or prev == blank_id):
            out.append(int(tok))
        prev = tok

    return tokenizer.decode(out)


def _infer_pred_state_shapes(
    pred_sess: rt.InferenceSession,
    fallback_hidden: int,
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """
    Возвращает shape для h и c.
    Стратегия:
    - если ORT shape задан (первый dim / скрытая размерность), используем
    - иначе fallback (1,1,fallback_hidden)
    """
    ins = pred_sess.get_inputs()
    if len(ins) < 3:
        return (1, 1, fallback_hidden), (1, 1, fallback_hidden)

    h_shape = ins[1].shape
    c_shape = ins[2].shape

    def normalize(sh):
        # sh может быть [1,1,768] или [None, None, 768] или [1,'batch',768]
        layers = sh[0] if isinstance(sh[0], int) else 1
        batch = sh[1] if isinstance(sh[1], int) else 1
        hid = sh[2] if isinstance(sh[2], int) else fallback_hidden
        return (int(layers), int(batch), int(hid))

    return normalize(h_shape), normalize(c_shape)


def _rnnt_greedy_decode(
    encoded: np.ndarray,         # [B, D, T]
    encoded_len: np.ndarray,     # [B]
    model_cfg: omegaconf.DictConfig,
    sessions: List[rt.InferenceSession],
    tokenizer: Tokenizer,
    max_letters_per_frame: int = MAX_LETTERS_PER_FRAME,
) -> str:
    if len(sessions) != 3:
        raise RuntimeError(f"RNNT expects 3 sessions (enc/dec/joint), got {len(sessions)}")

    _, pred_sess, joint_sess = sessions

    # blank id = len(tokenizer) (как в torch-ветке)
    blank_id = len(tokenizer)

    # pred_hidden нужен хотя бы для init state
    pred_hidden = int(model_cfg.head.decoder.pred_hidden)

    h_shape, c_shape = _infer_pred_state_shapes(pred_sess, fallback_hidden=pred_hidden)
    h = np.zeros(h_shape, dtype=DTYPE)
    c = np.zeros(c_shape, dtype=DTYPE)

    # важно: x всегда должен быть int64 для onnxruntime
    prev_token = int(blank_id)

    # encoded: [B,D,T], но мы декодируем первый элемент (B=1)
    T = int(encoded_len[0]) if encoded_len.size > 0 else int(encoded.shape[-1])
    token_ids: List[int] = []

    for t in range(T):
        emitted = 0
        while emitted < max_letters_per_frame:
            # decoder(x,h,c) -> dec,h,c
            dec_inputs = {
                pred_sess.get_inputs()[0].name: _np_i64([[prev_token]]),
                pred_sess.get_inputs()[1].name: h,
                pred_sess.get_inputs()[2].name: c,
            }
            dec_out, h_new, c_new = pred_sess.run(
                [o.name for o in pred_sess.get_outputs()],
                dec_inputs,
            )

            # dec_out: [B,1,pred_hidden] => нужно [B,pred_hidden,1]
            dec_for_joint = np.swapaxes(dec_out, 1, 2)

            # enc frame: [B,D,1]
            enc_frame = encoded[:, :, t : t + 1].astype(DTYPE)

            joint_inputs = {
                joint_sess.get_inputs()[0].name: enc_frame,
                joint_sess.get_inputs()[1].name: dec_for_joint.astype(DTYPE),
            }
            joint_out = joint_sess.run(
                [o.name for o in joint_sess.get_outputs()],
                joint_inputs,
            )[0]

            # joint_out обычно [B,1,1,C] или [B,1,C] (зависит от экспорта)
            # приводим к последней оси = C
            flat = joint_out.reshape(-1, joint_out.shape[-1])
            tok = int(flat[0].argmax(axis=-1))

            if tok == blank_id:
                break

            token_ids.append(tok)
            prev_token = tok
            h, c = h_new, c_new
            emitted += 1

    return tokenizer.decode(token_ids)


def infer_onnx(
    wav_file: str,
    model_cfg: omegaconf.DictConfig,
    sessions: List[rt.InferenceSession],
    preprocessor: Optional[FeatureExtractor] = None,
    tokenizer: Optional[Tokenizer] = None,
) -> Union[str, np.ndarray]:
    """
    Нормальный инференс ONNX:
    - грузим wav (ffmpeg) -> waveform
    - прогоняем preprocessor (torch) -> log-mel features
    - прогоняем ONNX сессии
    - декодируем CTC/RNNT greedily
    """
    model_name = str(model_cfg.model_name)

    if preprocessor is None:
        preprocessor = hydra.utils.instantiate(model_cfg.preprocessor)

    if tokenizer is None and ("ctc" in model_name or "rnnt" in model_name):
        tokenizer = hydra.utils.instantiate(model_cfg.decoding).tokenizer

    wav = load_audio(wav_file)  # torch.Tensor [samples], 16k
    wav_len = torch.tensor([wav.shape[-1]], dtype=torch.long)
    feats, feat_len = preprocessor(wav.unsqueeze(0), wav_len)  # [B,F,T], [B]
    feats_np = feats.detach().cpu().numpy().astype(DTYPE)
    feat_len_np = feat_len.detach().cpu().numpy().astype(np.int64)

    # --- encoder / full model ---
    enc_sess = sessions[0]
    enc_inputs = _build_ort_inputs(enc_sess, feats_np, feat_len_np)
    enc_outputs = enc_sess.run([o.name for o in enc_sess.get_outputs()], enc_inputs)

    if "emo" in model_name or "ssl" in model_name:
        # возвращаем фичи энкодера как есть
        return enc_outputs[0]

    if tokenizer is None:
        raise RuntimeError("Tokenizer is required for ASR models (ctc/rnnt).")

    if "ctc" in model_name and "rnnt" not in model_name:
        # ctc-экспорт: один граф, output = log_probs
        log_probs = enc_outputs[0]
        return _ctc_greedy_decode(log_probs, tokenizer)

    # rnnt-экспорт: encoder отдельно, плюс decoder/joint сессии
    if len(enc_outputs) >= 2:
        encoded = enc_outputs[0].astype(DTYPE)      # [B,D,T]
        encoded_len = enc_outputs[1].astype(np.int64)  # [B]
    else:
        encoded = enc_outputs[0].astype(DTYPE)
        encoded_len = _np_i64([encoded.shape[-1]])

    return _rnnt_greedy_decode(
        encoded=encoded,
        encoded_len=encoded_len,
        model_cfg=model_cfg,
        sessions=sessions,
        tokenizer=tokenizer,
        max_letters_per_frame=MAX_LETTERS_PER_FRAME,
    )


def transcribe_sample(
    wav_file: str,
    model_cfg: omegaconf.DictConfig,
    sessions: List[rt.InferenceSession],
    preprocessor: Optional[FeatureExtractor] = None,
    tokenizer: Optional[Tokenizer] = None,
) -> str:
    """
    Совместимая точка входа "transcribe_sample", но теперь это реальный инференс,
    а не заглушка. Возвращает текст.
    """
    out = infer_onnx(
        wav_file=wav_file,
        model_cfg=model_cfg,
        sessions=sessions,
        preprocessor=preprocessor,
        tokenizer=tokenizer,
    )
    if isinstance(out, str):
        return out
    raise RuntimeError(f"Expected ASR text output, got ndarray with shape={out.shape}")


def load_onnx(
    onnx_dir: str,
    model_version: str,
    providers: Optional[Union[str, List[str]]] = None,
) -> Tuple[List[rt.InferenceSession], Union[omegaconf.DictConfig, omegaconf.ListConfig]]:
    """
    Load ONNX sessions + yaml cfg.
    providers: строка или список провайдеров (например ["DmlExecutionProvider","CPUExecutionProvider"])
    """
    if providers is None:
        providers = ["CUDAExecutionProvider"] if "CUDAExecutionProvider" in rt.get_available_providers() else ["CPUExecutionProvider"]
    elif isinstance(providers, str):
        providers = [providers]
    else:
        providers = list(providers)

    if "CPUExecutionProvider" not in providers:
        providers.append("CPUExecutionProvider")

    opts = rt.SessionOptions()
    opts.intra_op_num_threads = 16
    opts.execution_mode = rt.ExecutionMode.ORT_SEQUENTIAL
    opts.log_severity_level = 3

    model_cfg = omegaconf.OmegaConf.load(f"{onnx_dir}/{model_version}.yaml")

    if "rnnt" not in model_version and "ssl" not in model_version and "emo" not in model_version:
        # ctc одним файлом
        model_path = f"{onnx_dir}/{model_version}.onnx"
        sessions = [rt.InferenceSession(model_path, providers=providers, sess_options=opts)]
        return sessions, model_cfg

    pth = f"{onnx_dir}/{model_version}"

    if "ssl" in model_version:
        enc_sess = rt.InferenceSession(f"{pth}_encoder.onnx", providers=providers, sess_options=opts)
        return [enc_sess], model_cfg

    if "emo" in model_version:
        # эмо-экспорт — один граф (по вашему model.py это {model_name}.onnx, но на всякий случай поддержим encoder)
        # если у вас реально сохраняется {model_version}.onnx — используйте ветку выше.
        enc_sess = rt.InferenceSession(f"{pth}_encoder.onnx", providers=providers, sess_options=opts)
        return [enc_sess], model_cfg

    # rnnt: encoder/decoder/joint
    enc_sess = rt.InferenceSession(f"{pth}_encoder.onnx", providers=providers, sess_options=opts)
    pred_sess = rt.InferenceSession(f"{pth}_decoder.onnx", providers=providers, sess_options=opts)
    joint_sess = rt.InferenceSession(f"{pth}_joint.onnx", providers=providers, sess_options=opts)
    return [enc_sess, pred_sess, joint_sess], model_cfg