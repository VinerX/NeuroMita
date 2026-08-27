from __future__ import annotations

from typing import Literal

import torch
import torch.nn.functional as F
from torch import nn
from x_transformers.x_transformers import RotaryEmbedding

from f5_tts.model.modules import (
    Attention,
    AttnProcessor,
    ConvPositionEmbedding,
    FeedForward,
    MelSpec,
)
from f5_tts.model.utils import default, exists, lens_to_mask


class SpeedPredictorLayer(nn.Module):
    def __init__(self, dim, heads, dim_head, ff_mult=4, dropout=0.1, qk_norm=None, pe_attn_head=None):
        super().__init__()
        self.attn = Attention(
            processor=AttnProcessor(pe_attn_head=pe_attn_head),
            dim=dim,
            heads=heads,
            dim_head=dim_head,
            dropout=dropout,
            qk_norm=qk_norm,
        )
        self.ln1 = nn.LayerNorm(dim, elementwise_affine=True, eps=1e-6)
        self.ln2 = nn.LayerNorm(dim, elementwise_affine=True, eps=1e-6)
        self.ff = FeedForward(dim=dim, mult=ff_mult, dropout=dropout, approximate="tanh")

    def forward(self, x, mask=None, rope=None):
        x = x + self.attn(x=self.ln1(x), mask=mask, rope=rope)
        return x + self.ff(x=self.ln2(x))


class SpeedTransformer(nn.Module):
    def __init__(
        self,
        dim,
        depth=6,
        heads=8,
        dropout=0.1,
        ff_mult=4,
        qk_norm=None,
        pe_attn_head=None,
        mel_dim=100,
        num_classes=32,
    ):
        super().__init__()
        dim_head = dim // heads
        self.mel_proj = nn.Linear(mel_dim, dim)
        self.conv_layer = ConvPositionEmbedding(dim=dim)
        self.rotary_embed = RotaryEmbedding(dim_head)
        self.transformer_blocks = nn.ModuleList(
            [
                SpeedPredictorLayer(
                    dim=dim,
                    heads=heads,
                    dim_head=dim_head,
                    ff_mult=ff_mult,
                    dropout=dropout,
                    qk_norm=qk_norm,
                    pe_attn_head=pe_attn_head,
                )
                for _ in range(depth)
            ]
        )
        self.pool = nn.Sequential(nn.Linear(dim, dim), nn.Tanh(), nn.Linear(dim, 1))
        self.classifier = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, dim),
            nn.GELU(),
            nn.Linear(dim, num_classes),
        )

    def forward(self, x, lens):
        seq_len = x.shape[1]
        mask = lens_to_mask(lens, length=seq_len)
        x = self.conv_layer(self.mel_proj(x), mask)
        rope = self.rotary_embed.forward_from_seq_len(seq_len)
        for block in self.transformer_blocks:
            x = block(x, mask=mask, rope=rope)

        weights = self.pool(x)
        weights.masked_fill_(~mask.unsqueeze(-1), -torch.finfo(weights.dtype).max)
        x = (x * F.softmax(weights, dim=1)).sum(dim=1)
        return self.classifier(x)


class SpeedMapper:
    def __init__(self, num_classes: Literal[32, 72], delta: float = 0.25):
        self.speed_values = torch.arange(0.25, float(num_classes) * delta + delta, delta)
        if len(self.speed_values) != num_classes:
            raise ValueError(f"Generated {len(self.speed_values)} classes, expected {num_classes}")

    def label_to_speed(self, label: torch.Tensor) -> torch.Tensor:
        return self.speed_values.to(label.device)[label]


class SpeedPredictor(nn.Module):
    def __init__(
        self,
        speed_type: Literal["phonemes", "syllables", "words"] = "syllables",
        mel_spec_kwargs: dict | None = None,
        arch_kwargs: dict | None = None,
        mel_spec_module: nn.Module | None = None,
        num_channels: int | None = None,
    ):
        super().__init__()
        num_classes = {"phonemes": 72, "syllables": 32, "words": 32}[speed_type]
        self.mel_spec = default(mel_spec_module, MelSpec(**(mel_spec_kwargs or {})))
        self.num_channels = default(num_channels, self.mel_spec.n_mel_channels)
        self.speed_transformer = SpeedTransformer(**(arch_kwargs or {}), num_classes=num_classes)
        self.speed_mapper = SpeedMapper(num_classes)

    @torch.no_grad()
    def predict_speed(self, audio: torch.Tensor, lens: torch.Tensor | None = None):
        if audio.ndim == 2:
            audio = self.mel_spec(audio).permute(0, 2, 1)
        batch, seq_len = audio.shape[:2]
        if not exists(lens):
            lens = torch.full((batch,), seq_len, device=audio.device, dtype=torch.long)
        logits = self.speed_transformer(audio, lens)
        return self.speed_mapper.label_to_speed(torch.argmax(F.softmax(logits, dim=-1), dim=-1))
