import re

from utils.throttled_progress_logger import ThrottledProgressLogger


def rag_clean_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""

    t = text

    # 1) убрать memory-команды целиком (обычно с закрывающим </memory>)
    t = re.sub(r"<[+\-#]memory>.*?</memory>", " ", t, flags=re.S | re.I)

    # 2) убрать pose/числовые векторы (часто повторяющиеся)
    t = re.sub(r"<p>\s*[-0-9\.,\s]+\s*</p>", " ", t, flags=re.I)

    # 3) убрать сами теги, но оставить внутренний текст
    t = re.sub(r"</?[^>]+>", " ", t)

    # 4) схлопнуть пробелы
    t = re.sub(r"\s+", " ", t).strip()
    return t


def make_reindex_progress_logger(rag_manager, op: str, total: int, extra_meta: str = "") -> ThrottledProgressLogger:
    log_every = rag_manager._get_int_setting("RAG_REINDEX_LOG_EVERY", 50)
    log_interval = rag_manager._get_float_setting("RAG_REINDEX_LOG_INTERVAL_SEC", 5.0)
    if log_every <= 0:
        log_every = 50
    if log_interval <= 0:
        log_interval = 5.0

    meta = f"character_id={rag_manager.character_id}"
    if extra_meta:
        meta = f"{meta} | {extra_meta}"

    return ThrottledProgressLogger(
        info=logger.info,
        op=f"[RAG] {op}",
        total=int(total),
        meta=meta,
        log_every=int(log_every),
        log_interval_sec=float(log_interval),
    )