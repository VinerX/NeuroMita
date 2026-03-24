"""Cross-encoder reranker for RAG pipeline (optional second pass).

Loads a sequence-classification model (e.g. ms-marco-MiniLM-L-6-v2) that
scores (query, passage) pairs with a single relevance logit.  Runs on the
top-K candidates returned by the first LinearReranker pass and replaces
their scores in-place.

Also supports LM-based rerankers (e.g. Qwen3-Reranker-0.6B) that use
yes/no token probabilities from a causal LM for scoring.

Model is loaded lazily and cached as a per-model-name singleton so it is
loaded at most once per process (same pattern as EmbeddingModelHandler).
"""
from __future__ import annotations

import os
import sys
from threading import Lock
from typing import Optional

from main_logger import logger


# Model names (or substrings) that use AutoModelForCausalLM + yes/no scoring
_LM_RERANKER_PATTERNS = (
    "qwen3-reranker",
    "qwen/qwen3-reranker",
)


def _is_lm_reranker(model_name: str) -> bool:
    """Return True if model_name is a known LM-based reranker."""
    lower = model_name.lower()
    return any(p in lower for p in _LM_RERANKER_PATTERNS)


def _checkpoints_dir() -> str:
    return os.path.join(os.path.dirname(sys.executable), "checkpoints")


class CrossEncoderReranker:
    """Singleton per model_name.  Call CrossEncoderReranker.get(name)."""

    _instances: dict[str, "CrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._load_lock = Lock()
        self._failed = False  # skip retries after a permanent failure
        self._is_lm = _is_lm_reranker(model_name)  # LM-based yes/no scorer
        self._token_true_id: Optional[int] = None
        self._token_false_id: Optional[int] = None
        self._device = None  # set on first load

    # ------------------------------------------------------------------ #
    @classmethod
    def get(cls, model_name: str) -> "CrossEncoderReranker":
        if model_name not in cls._instances:
            with cls._cls_lock:
                if model_name not in cls._instances:
                    cls._instances[model_name] = cls(model_name)
        return cls._instances[model_name]

    # ------------------------------------------------------------------ #
    def _ensure_loaded(self) -> bool:
        """Lazy load; returns True if model is ready."""
        if self._model is not None:
            return True
        if self._failed:
            return False
        with self._load_lock:
            if self._model is not None:
                return True
            if self._failed:
                return False
            try:
                import torch
                cache_dir = _checkpoints_dir()
                from managers.settings_manager import SettingsManager
                token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None
                logger.info(
                    f"[CrossEncoder] Loading '{self.model_name}' "
                    f"(lm_mode={self._is_lm}, cache: {cache_dir}) ..."
                )
                dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

                if self._is_lm:
                    from transformers import AutoTokenizer, AutoModelForCausalLM
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name, cache_dir=cache_dir, token=token,
                        trust_remote_code=True, padding_side="left",
                    )
                    self._model = AutoModelForCausalLM.from_pretrained(
                        self.model_name, cache_dir=cache_dir, token=token,
                        trust_remote_code=True, torch_dtype=dtype,
                    )
                    self._token_true_id = self._tokenizer.convert_tokens_to_ids("yes")
                    self._token_false_id = self._tokenizer.convert_tokens_to_ids("no")
                    logger.info(
                        f"[CrossEncoder] LM reranker ready: "
                        f"yes={self._token_true_id}, no={self._token_false_id}"
                    )
                else:
                    from transformers import AutoTokenizer, AutoModelForSequenceClassification
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name, cache_dir=cache_dir, token=token,
                        trust_remote_code=True,
                    )
                    self._model = AutoModelForSequenceClassification.from_pretrained(
                        self.model_name, cache_dir=cache_dir, token=token,
                        trust_remote_code=True, torch_dtype=dtype,
                    )

                self._model.to(device)
                self._device = device
                self._model.eval()
                logger.info(f"[CrossEncoder] Model '{self.model_name}' ready (device={device}).")
                return True
            except Exception as exc:
                logger.warning(
                    f"[CrossEncoder] Failed to load '{self.model_name}': {exc} "
                    "(cross-encoder reranking disabled)"
                )
                self._failed = True
                return False

    # ------------------------------------------------------------------ #
    _QWEN3_RERANKER_INSTRUCTION = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )

    def _score_seqcls(self, query: str, cands: list) -> list:
        """Score with AutoModelForSequenceClassification (standard cross-encoder)."""
        import torch
        pairs = [(query, str(c.content or "")) for c in cands]
        enc = self._tokenizer(
            [p[0] for p in pairs],
            [p[1] for p in pairs],
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            logits = self._model(**enc).logits  # (N, num_labels)
        if logits.shape[-1] == 1:
            raw = logits.squeeze(-1)
        else:
            raw = logits[:, -1]
        return raw.tolist()

    def _score_lm(self, query: str, cands: list) -> list:
        """Score with LM-based reranker (Qwen3-Reranker style yes/no tokens)."""
        import torch

        instruction = self._QWEN3_RERANKER_INSTRUCTION
        prefix = (
            "<|im_start|>system\n"
            "Judge whether the Document meets the requirements based on the Query and "
            "the Instruct provided. Note that the answer can only be \"yes\" or \"no\"."
            "<|im_end|>\n<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

        input_texts = []
        for c in cands:
            doc = str(c.content or "")
            content = f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"
            input_texts.append(prefix + content + suffix)

        enc = self._tokenizer(
            input_texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            logits = self._model(**enc).logits  # (N, vocab_size)

        # Extract yes/no logits at last token position
        last_logits = logits[:, -1, :]  # (N, vocab_size)
        true_id = self._token_true_id
        false_id = self._token_false_id
        pair = torch.stack([last_logits[:, false_id], last_logits[:, true_id]], dim=-1)
        probs = torch.softmax(pair, dim=-1)  # (N, 2)
        return probs[:, 1].tolist()  # P(yes)

    # ------------------------------------------------------------------ #
    def rerank(self, query: str, cands: list, top_k: int = 20, alpha: float = 1.0) -> None:
        """Re-score cands[:top_k] in-place with cross-encoder logits.

        final_score = alpha * CE_score + (1 - alpha) * linear_score
        alpha=1.0 → pure CE (old behaviour).
        alpha<1.0 → protects high-linear-score docs from CE errors.

        After this call the caller should re-sort cands by score.
        Candidates beyond top_k are left untouched (their original linear
        scores are kept so they stay below the re-ranked ones).
        """
        if not cands or not query:
            return
        if not self._ensure_loaded():
            return

        to_score = cands[:top_k]

        try:
            if self._is_lm:
                scores = self._score_lm(query, to_score)
            else:
                scores = self._score_seqcls(query, to_score)

            # Pre-compute normalized linear scores (MinMax → 0..1) for alpha-mixing.
            # This ensures CE (0..1) and linear (arbitrary scale) are comparable.
            if alpha < 1.0:
                raw_linear = [float((c.debug or {}).get("final", c.score)) for c in to_score]
                ls_min = min(raw_linear)
                ls_max = max(raw_linear)
                ls_range = ls_max - ls_min
                norm_linear = [
                    (s - ls_min) / ls_range if ls_range > 1e-9 else 0.5
                    for s in raw_linear
                ]
            else:
                norm_linear = None

            # Determine position changes before modifying scores
            post_order = sorted(range(len(to_score)), key=lambda i: scores[i], reverse=True)
            moves = []
            for new_pos, old_pos in enumerate(post_order):
                if old_pos != new_pos:
                    c = to_score[old_pos]
                    moves.append(f"{c.source}:{c.id} {old_pos+1}→{new_pos+1}")

            for i, (c, s) in enumerate(zip(to_score, scores)):
                ce_score = float(s)
                if alpha < 1.0:
                    mixed = alpha * ce_score + (1.0 - alpha) * norm_linear[i]
                else:
                    mixed = ce_score
                c.score = mixed
                if c.debug is None:
                    c.debug = {}
                c.debug["cross_encoder"] = ce_score

            if moves:
                logger.info(
                    f"[CrossEncoder] Re-ranked {len(to_score)}/{len(cands)} | "
                    f"top={max(scores):.3f} | moves: " + ", ".join(moves[:10])
                    + (f" (+{len(moves)-10} more)" if len(moves) > 10 else "")
                )
            else:
                logger.info(
                    f"[CrossEncoder] Re-ranked {len(to_score)}/{len(cands)} | "
                    f"top={max(scores):.3f} | no position changes"
                )
        except Exception as exc:
            logger.warning(f"[CrossEncoder] predict failed (ignored): {exc}")
