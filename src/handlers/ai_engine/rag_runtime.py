from __future__ import annotations

import gc
import os
import sys
from threading import Lock
from typing import Any, Optional

from main_logger import logger


_LM_RERANKER_PATTERNS = (
    "qwen3-reranker",
    "qwen/qwen3-reranker",
)


def _is_lm_reranker(model_name: str) -> bool:
    lower = str(model_name or "").lower()
    return any(p in lower for p in _LM_RERANKER_PATTERNS)


def _checkpoints_dir() -> str:
    val = os.environ.get("NEUROMITA_CHECKPOINTS_DIR")
    if val:
        return val
    base = os.environ.get("NEUROMITA_BASE_DIR")
    if base:
        return os.path.join(base, "checkpoints")
    return os.path.join(os.path.dirname(sys.executable), "checkpoints")


def shutdown_rag_runtime() -> None:
    embedding_module = sys.modules.get("handlers.embedding_handler")
    embedding_handler = getattr(embedding_module, "EmbeddingModelHandler", None)
    if embedding_handler is not None:
        embedding_handler._unload_shared()

    WorkerCrossEncoderReranker.clear_all()

    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


class WorkerCrossEncoderReranker:
    _instances: dict[str, "WorkerCrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()

    _QWEN3_RERANKER_INSTRUCTION = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    _BATCH_SIZE_LM: int = 16
    _BATCH_SIZE_SEQCLS: int = 32

    def __init__(self, model_name: str) -> None:
        self.model_name = str(model_name or "")
        self._tokenizer = None
        self._model = None
        self._load_lock = Lock()
        self._failed = False
        self._is_lm = _is_lm_reranker(model_name)
        self._token_true_id: Optional[int] = None
        self._token_false_id: Optional[int] = None
        self._device = None

    @classmethod
    def get(cls, model_name: str) -> "WorkerCrossEncoderReranker":
        model_name = str(model_name or "")
        if model_name not in cls._instances:
            with cls._cls_lock:
                if model_name not in cls._instances:
                    cls._instances[model_name] = cls(model_name)
        return cls._instances[model_name]

    @classmethod
    def status(cls, model_name: str) -> dict[str, Any]:
        inst = cls._instances.get(str(model_name or ""))
        return {
            "loaded": bool(inst and inst._model is not None),
            "failed": bool(inst and inst._failed),
        }

    @classmethod
    def clear_all(cls) -> None:
        cls._instances.clear()

    def _ensure_loaded(self) -> bool:
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
                from managers.rag.install_spec import TARGET_RERANKER, ensure_runtime_ready
                from managers.settings_manager import SettingsManager

                ensure_runtime_ready(TARGET_RERANKER)
                import torch

                cache_dir = _checkpoints_dir()
                token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None
                logger.info(
                    f"[RAG][CrossEncoder] Loading '{self.model_name}' "
                    f"(lm_mode={self._is_lm}, cache={cache_dir})"
                )

                dtype = torch.float16 if torch.cuda.is_available() else torch.float32
                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

                use_int8 = False
                if not self._is_lm and torch.cuda.is_available():
                    try:
                        raw = str(SettingsManager.get("RAG_CE_INT8", False) or "")
                        use_int8 = raw.strip().lower() in ("1", "true", "yes", "on")
                    except Exception:
                        pass

                if self._is_lm:
                    from transformers import AutoModelForCausalLM, AutoTokenizer

                    self._tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name,
                        cache_dir=cache_dir,
                        token=token,
                        trust_remote_code=True,
                        padding_side="left",
                    )
                    self._model = AutoModelForCausalLM.from_pretrained(
                        self.model_name,
                        cache_dir=cache_dir,
                        token=token,
                        trust_remote_code=True,
                        torch_dtype=dtype,
                    )
                    self._token_true_id = self._tokenizer.convert_tokens_to_ids("yes")
                    self._token_false_id = self._tokenizer.convert_tokens_to_ids("no")
                    self._model.to(device)
                    self._device = device
                elif use_int8:
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer

                    self._tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name,
                        cache_dir=cache_dir,
                        token=token,
                        trust_remote_code=True,
                    )
                    try:
                        import bitsandbytes  # noqa: F401

                        self._model = AutoModelForSequenceClassification.from_pretrained(
                            self.model_name,
                            cache_dir=cache_dir,
                            token=token,
                            trust_remote_code=True,
                            load_in_8bit=True,
                            device_map="auto",
                        )
                        self._device = torch.device("cuda")
                        logger.info("[RAG][CrossEncoder] INT8 quantization active.")
                    except ImportError:
                        logger.warning("[RAG][CrossEncoder] bitsandbytes not installed, falling back to float16.")
                        self._model = AutoModelForSequenceClassification.from_pretrained(
                            self.model_name,
                            cache_dir=cache_dir,
                            token=token,
                            trust_remote_code=True,
                            torch_dtype=dtype,
                        )
                        self._model.to(device)
                        self._device = device
                else:
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer

                    self._tokenizer = AutoTokenizer.from_pretrained(
                        self.model_name,
                        cache_dir=cache_dir,
                        token=token,
                        trust_remote_code=True,
                    )
                    self._model = AutoModelForSequenceClassification.from_pretrained(
                        self.model_name,
                        cache_dir=cache_dir,
                        token=token,
                        trust_remote_code=True,
                        torch_dtype=dtype,
                    )
                    self._model.to(device)
                    self._device = device

                self._model.eval()
                logger.info(f"[RAG][CrossEncoder] Ready '{self.model_name}' on {self._device}.")
                return True
            except Exception as exc:
                logger.warning(
                    f"[RAG][CrossEncoder] Failed to load '{self.model_name}': {exc} "
                    "(cross-encoder disabled)"
                )
                self._failed = True
                return False

    def _candidate_content(self, candidate: dict[str, Any]) -> str:
        return str((candidate or {}).get("content") or "")

    def _score_seqcls(self, query: str, candidates: list[dict[str, Any]], early_exit_score: float = 1.1) -> list[float]:
        import torch

        pairs = [(query, self._candidate_content(c)) for c in candidates]
        all_scores: list[float] = []
        for i in range(0, len(pairs), self._BATCH_SIZE_SEQCLS):
            batch = pairs[i:i + self._BATCH_SIZE_SEQCLS]
            enc = self._tokenizer(
                [p[0] for p in batch],
                [p[1] for p in batch],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self._device)
            with torch.no_grad():
                logits = self._model(**enc).logits
            raw = logits.squeeze(-1) if logits.shape[-1] == 1 else logits[:, -1]
            all_scores.extend(raw.tolist())
            if (
                early_exit_score <= 1.0
                and len(all_scores) >= self._BATCH_SIZE_SEQCLS
                and max(all_scores) >= early_exit_score
            ):
                break
        return all_scores

    def _score_lm(self, query: str, candidates: list[dict[str, Any]], early_exit_score: float = 1.1) -> list[float]:
        import torch

        prefix = (
            "<|im_start|>system\n"
            "Judge whether the Document meets the requirements based on the Query and "
            "the Instruct provided. Note that the answer can only be \"yes\" or \"no\"."
            "<|im_end|>\n<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

        prompts = []
        for candidate in candidates:
            content = (
                f"<Instruct>: {self._QWEN3_RERANKER_INSTRUCTION}\n"
                f"<Query>: {query}\n"
                f"<Document>: {self._candidate_content(candidate)}"
            )
            prompts.append(prefix + content + suffix)

        true_id = self._token_true_id
        false_id = self._token_false_id
        all_probs: list[float] = []

        for i in range(0, len(prompts), self._BATCH_SIZE_LM):
            batch = prompts[i:i + self._BATCH_SIZE_LM]
            enc = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self._device)
            with torch.no_grad():
                logits = self._model(**enc).logits
            last_logits = logits[:, -1, :]
            pair = torch.stack([last_logits[:, false_id], last_logits[:, true_id]], dim=-1)
            probs = torch.softmax(pair, dim=-1)
            all_probs.extend(probs[:, 1].tolist())
            if (
                early_exit_score <= 1.0
                and len(all_probs) >= self._BATCH_SIZE_LM
                and max(all_probs) >= early_exit_score
            ):
                break
        return all_probs

    def rerank_payload(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_k: int,
        alpha: float,
        early_exit_score: float,
        total_candidates: int,
    ) -> dict[str, Any]:
        if not candidates or not query:
            return {"updates": [], "loaded": bool(self._model is not None)}
        if not self._ensure_loaded():
            return {"updates": [], "loaded": False, "failed": True}

        top_k = max(1, int(top_k or 1))
        alpha = max(0.0, min(1.0, float(alpha or 0.0)))
        early_exit_score = float(early_exit_score or 0.0)

        to_score = list(candidates[:top_k])
        if self._is_lm:
            scores = self._score_lm(query, to_score, early_exit_score=early_exit_score)
        else:
            scores = self._score_seqcls(query, to_score, early_exit_score=early_exit_score)

        n_scored = len(scores)
        scored_cands = to_score[:n_scored]

        if alpha < 1.0 and scored_cands:
            raw_linear = []
            for candidate in scored_cands:
                debug = candidate.get("debug") if isinstance(candidate.get("debug"), dict) else {}
                raw_linear.append(float(debug.get("final", candidate.get("score", 0.0)) or 0.0))
            ls_min = min(raw_linear)
            ls_max = max(raw_linear)
            ls_range = ls_max - ls_min
            norm_linear = [
                (score - ls_min) / ls_range if ls_range > 1e-9 else 0.5
                for score in raw_linear
            ]
        else:
            norm_linear = None

        moves = []
        post_order = sorted(range(n_scored), key=lambda i: scores[i], reverse=True)
        for new_pos, old_pos in enumerate(post_order):
            if old_pos != new_pos:
                candidate = scored_cands[old_pos]
                moves.append(
                    f"{candidate.get('source')}:{candidate.get('id')} {old_pos + 1}->{new_pos + 1}"
                )

        updates = []
        for i, (candidate, score) in enumerate(zip(scored_cands, scores)):
            ce_score = float(score)
            if alpha < 1.0 and norm_linear is not None:
                final_score = alpha * ce_score + (1.0 - alpha) * norm_linear[i]
            else:
                final_score = ce_score
            updates.append(
                {
                    "index": i,
                    "score": final_score,
                    "cross_encoder": ce_score,
                }
            )

        total = int(total_candidates or len(candidates))
        if scores:
            early_exit_note = (
                f" [early_exit: scored {n_scored}/{len(to_score)}]"
                if n_scored < len(to_score) else ""
            )
            if moves:
                logger.info(
                    f"[RAG][CrossEncoder] Re-ranked {n_scored}/{total}{early_exit_note} | "
                    f"top={max(scores):.3f} | moves: " + ", ".join(moves[:10])
                    + (f" (+{len(moves) - 10} more)" if len(moves) > 10 else "")
                )
            else:
                logger.info(
                    f"[RAG][CrossEncoder] Re-ranked {n_scored}/{total}{early_exit_note} | "
                    f"top={max(scores):.3f} | no position changes"
                )

        return {
            "updates": updates,
            "loaded": True,
            "scored": n_scored,
        }
