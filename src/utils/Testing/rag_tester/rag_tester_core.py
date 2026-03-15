from __future__ import annotations

import json
import datetime
from dataclasses import dataclass
from typing import Any, Optional

from managers.database_manager import DatabaseManager
from managers.rag.rag_manager import RAGManager
from managers.history_manager import HistoryManager
from managers.memory_manager import MemoryManager
from managers.settings_manager import SettingsManager


def now_ts() -> str:
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def as_stripped(v: Any) -> str:
    return str(v or "").strip()


def safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


class SettingsOverride:
    """
    Временный override SettingsManager.get(key, default), чтобы тестировать RAG
    с разными весами/настройками "как в проде", не меняя код RAGManager.
    """
    def __init__(self, overrides: dict[str, Any]):
        self.overrides = dict(overrides or {})
        self._orig_get = None

    def __enter__(self):
        self._orig_get = getattr(SettingsManager, "get", None)
        orig = self._orig_get

        def wrapped_get(key: str, default=None):
            k = str(key) if key is not None else ""
            if k in self.overrides:
                return self.overrides[k]
            if callable(orig):
                return orig(key, default)
            return default

        try:
            setattr(SettingsManager, "get", staticmethod(wrapped_get))
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._orig_get is not None:
                setattr(SettingsManager, "get", self._orig_get)
        except Exception:
            pass
        return False


@dataclass
class Scenario:
    character_id: str
    context: list[dict]    # history.is_active=1
    history: list[dict]    # history.is_active=0 (корпус для RAG)
    memories: list[dict]   # memories

    @staticmethod
    def template(character_id: str = "RAG_TEST") -> "Scenario":
        cid = character_id or "RAG_TEST"
        t = now_ts()
        return Scenario(
            character_id=cid,
            context=[
                {
                    "message_id": "in:demo-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": cid,
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": t,
                    "content": [{"type": "text", "text": "Привет! Напомни, что я говорил про поездку в Альпы?"}],
                },
                {
                    "message_id": "out:demo-1",
                    "role": "assistant",
                    "speaker": cid,
                    "sender": cid,
                    "target": "Player",
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": t,
                    "content": "Ты говорил, что хочешь в Альпы весной и уже выбирал маршрут.",
                },
            ],
            history=[
                {
                    "message_id": "in:old-1",
                    "role": "user",
                    "speaker": "Player",
                    "sender": "Player",
                    "target": cid,
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": "01.12.2025 12:00:00",
                    "content": [{"type": "text", "text": "Я люблю горы, особенно Альпы."}],
                },
                {
                    "message_id": "out:old-1",
                    "role": "assistant",
                    "speaker": cid,
                    "sender": cid,
                    "target": "Player",
                    "participants": ["Player", cid],
                    "event_type": "chat",
                    "time": "01.12.2025 12:01:00",
                    "content": "Ты говорил, что хочешь в Швейцарию весной.",
                },
            ],
            memories=[
                {
                    "content": "User prefers mountains; wants Alps/Switzerland trip in spring.",
                    "priority": "High",
                    "type": "fact",
                    "date_created": "01.12.2025 12:05:00",
                    "is_forgotten": 1,  # чтобы попадало при RAG_MEMORY_MODE='forgotten'
                }
            ],
        )

    @staticmethod
    def from_json(obj: Any, fallback_character_id: str) -> "Scenario":
        if not isinstance(obj, dict):
            raise ValueError("Scenario JSON должен быть объектом (dict).")

        cid = as_stripped(obj.get("character_id") or fallback_character_id or "RAG_TEST") or "RAG_TEST"
        context = obj.get("context") or []
        history = obj.get("history") or []
        memories = obj.get("memories") or []

        if not isinstance(context, list) or not isinstance(history, list) or not isinstance(memories, list):
            raise ValueError("context/history/memories должны быть списками.")

        def norm_msgs(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if not isinstance(it, dict):
                    continue
                it2 = dict(it)
                if "timestamp" not in it2 and "time" not in it2:
                    it2["time"] = now_ts()
                it2.setdefault("role", "user")
                it2.setdefault("content", "")
                out.append(it2)
            return out

        def norm_mems(arr: list[Any]) -> list[dict]:
            out: list[dict] = []
            for it in arr:
                if isinstance(it, str):
                    s = it.strip()
                    if not s:
                        continue
                    out.append({
                        "content": s,
                        "priority": "Normal",
                        "type": "fact",
                        "date_created": now_ts(),
                        "is_forgotten": 1,
                    })
                    continue

                if not isinstance(it, dict):
                    continue

                content = as_stripped(it.get("content") or it.get("text") or it.get("memory"))
                if not content:
                    continue

                it2 = dict(it)
                it2["content"] = content
                it2.setdefault("priority", "Normal")
                it2.setdefault("type", "fact")
                it2.setdefault("date_created", now_ts())
                it2.setdefault("is_forgotten", 1)
                out.append(it2)

            return out

        return Scenario(
            character_id=cid,
            context=norm_msgs(context),
            history=norm_msgs(history),
            memories=norm_mems(memories),
        )

    def to_pretty_json(self) -> str:
        return json.dumps(
            {
                "character_id": self.character_id,
                "context": self.context,
                "history": self.history,
                "memories": self.memories,
            },
            ensure_ascii=False,
            indent=2,
        )


class RagTesterService:
    """
    Логика тестера (Model/Presenter):
    - I/O сценария (scenario JSON)
    - импорт legacy history/memories JSON
    - загрузка/выгрузка в DB
    - индексирование
    - поиск + prod-like overrides + превью инжекта
    """
    def __init__(self):
        self.db = DatabaseManager()

    # -------------------------
    # Scenario file helpers
    # -------------------------
    def load_scenario_file(self, path: str, fallback_character_id: str) -> Scenario:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.loads(f.read())
        return Scenario.from_json(obj, fallback_character_id=fallback_character_id)

    def save_scenario_file(self, scenario: Scenario, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(scenario.to_pretty_json())

    # -------------------------
    # Legacy import
    # -------------------------
    def import_old_history_obj(self, obj: Any, *, character_id: str, tail_to_context: int) -> Scenario:
        messages = None
        if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
            messages = obj.get("messages")
        elif isinstance(obj, list):
            messages = obj
        else:
            raise ValueError("Не похоже на history JSON: ожидаю list или dict с ключом 'messages'.")

        tail_n = max(0, int(tail_to_context))
        msgs_norm: list[dict] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            m2 = dict(m)
            if "timestamp" not in m2 and "time" not in m2:
                m2["time"] = now_ts()
            m2.setdefault("role", "user")
            m2.setdefault("content", "")
            msgs_norm.append(m2)

        if tail_n > 0:
            ctx = msgs_norm[-tail_n:] if len(msgs_norm) >= tail_n else list(msgs_norm)
            hist = msgs_norm[:-tail_n] if len(msgs_norm) > tail_n else []
        else:
            ctx, hist = [], msgs_norm

        return Scenario(character_id=character_id, context=ctx, history=hist, memories=[])

    def import_old_memories_obj(self, obj: Any, *, character_id: str) -> Scenario:
        mem_list = None
        if isinstance(obj, dict) and isinstance(obj.get("memories"), list):
            mem_list = obj.get("memories")
        elif isinstance(obj, list):
            mem_list = obj
        else:
            raise ValueError("Не похоже на memories JSON: ожидаю list или dict с ключом 'memories'.")

        mems: list[dict] = []
        for it in mem_list:
            if isinstance(it, str):
                s = it.strip()
                if s:
                    mems.append({
                        "content": s,
                        "priority": "Normal",
                        "type": "fact",
                        "date_created": now_ts(),
                        "is_forgotten": 1,
                    })
                continue
            if isinstance(it, dict):
                content = as_stripped(it.get("content") or it.get("text") or it.get("memory"))
                if not content:
                    continue
                d = dict(it)
                d["content"] = content
                d.setdefault("priority", "Normal")
                d.setdefault("type", "fact")
                d.setdefault("date_created", now_ts())
                d.setdefault("is_forgotten", 1)
                mems.append(d)

        return Scenario(character_id=character_id, context=[], history=[], memories=mems)

    def merge_scenarios(self, base: Scenario, add: Scenario, *, replace: bool) -> Scenario:
        if replace:
            return Scenario(
                character_id=add.character_id or base.character_id,
                context=list(add.context),
                history=list(add.history),
                memories=list(add.memories),
            )
        cid = add.character_id or base.character_id
        return Scenario(
            character_id=cid,
            context=list(base.context) + list(add.context),
            history=list(base.history) + list(add.history),
            memories=list(base.memories) + list(add.memories),
        )

    # -------------------------
    # DB helpers
    # -------------------------
    def table_cols(self, table: str) -> set[str]:
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception:
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def clear_character_data(self, character_id: str) -> None:
        cid = str(character_id)

        hcols = self.table_cols("history")
        mcols = self.table_cols("memories")

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()

            if "is_deleted" in hcols:
                cur.execute("UPDATE history SET is_deleted=1 WHERE character_id=?", (cid,))
            else:
                cur.execute("DELETE FROM history WHERE character_id=?", (cid,))

            try:
                cur.execute("DELETE FROM variables WHERE character_id=?", (cid,))
            except Exception:
                pass

            if "is_deleted" in mcols:
                cur.execute("UPDATE memories SET is_deleted=1 WHERE character_id=?", (cid,))
            else:
                cur.execute("DELETE FROM memories WHERE character_id=?", (cid,))

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def insert_history_messages(self, cid: str, msgs: list[dict], *, is_active: int, embed_now: bool) -> int:
        if not msgs:
            return 0

        hm = HistoryManager(character_name=cid, character_id=cid)
        rag = RAGManager(cid)

        inserted = 0
        for msg in msgs:
            if not isinstance(msg, dict):
                continue

            m2 = dict(msg)
            if "timestamp" not in m2 and "time" not in m2:
                m2["time"] = now_ts()
            m2.setdefault("role", "user")
            m2.setdefault("content", "")

            row_id = hm._insert_history_row(msg=m2, is_active=int(is_active))
            if row_id:
                inserted += 1
                if embed_now:
                    try:
                        txt = hm._extract_text_for_embedding(m2.get("content"))
                        if txt:
                            rag.update_history_embedding(int(row_id), txt)
                    except Exception:
                        pass

        return inserted

    def insert_memories(self, cid: str, memories: list[dict], *, embed_now: bool) -> int:
        if not memories:
            return 0

        # best-effort schema upgrade for is_forgotten
        _ = MemoryManager(cid)
        rag = RAGManager(cid)

        cols = self.table_cols("memories")
        has_is_forgotten = "is_forgotten" in cols
        has_is_deleted = "is_deleted" in cols

        inserted = 0
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(eternal_id) FROM memories WHERE character_id=?", (cid,))
            res = cur.fetchone()
            max_eid = int(res[0] or 0) if res else 0

            for it in memories:
                if not isinstance(it, dict):
                    continue
                content = as_stripped(it.get("content"))
                if not content:
                    continue

                max_eid += 1
                priority = as_stripped(it.get("priority") or "Normal") or "Normal"
                mtype = as_stripped(it.get("type") or "fact") or "fact"
                date_created = as_stripped(it.get("date_created") or now_ts()) or now_ts()
                participants = it.get("participants", None)
                is_forgotten = safe_int(it.get("is_forgotten"), 0)
                is_deleted = safe_int(it.get("is_deleted"), 0)

                insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created"]
                vals: list[Any] = [cid, max_eid, content, priority, mtype, date_created]

                if "participants" in cols:
                    insert_cols.append("participants")
                    vals.append(json.dumps(participants, ensure_ascii=False) if isinstance(participants, list) else participants)

                if has_is_deleted:
                    insert_cols.append("is_deleted")
                    vals.append(is_deleted)

                if has_is_forgotten:
                    insert_cols.append("is_forgotten")
                    vals.append(is_forgotten)

                placeholders = ",".join(["?"] * len(insert_cols))
                sql = f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})"
                cur.execute(sql, tuple(vals))
                inserted += 1

                if embed_now:
                    try:
                        rag.update_memory_embedding(max_eid, content)
                    except Exception:
                        pass

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return inserted

    def apply_scenario_to_db(self, scenario: Scenario, *, clear_before: bool, embed_now: bool) -> dict[str, int]:
        cid = scenario.character_id
        if clear_before:
            self.clear_character_data(cid)

        n_ctx = self.insert_history_messages(cid, scenario.context, is_active=1, embed_now=embed_now)
        n_hist = self.insert_history_messages(cid, scenario.history, is_active=0, embed_now=embed_now)
        n_mem = self.insert_memories(cid, scenario.memories, embed_now=embed_now)

        return {"context": n_ctx, "history": n_hist, "memories": n_mem}

    def load_scenario_from_db(self, cid: str, *, hist_limit: int, mem_limit: int) -> Scenario:
        cid = str(cid or "").strip() or "RAG_TEST"

        hm = HistoryManager(character_name=cid, character_id=cid)
        hm._ensure_history_schema()

        # active messages (context)
        active = hm.load_history().get("messages", []) or []

        # archived corpus (is_active=0)
        select_cols = hm._history_select_columns()
        cols_set = set(select_cols)
        hcols = hm._history_cols or set()

        where = "character_id=? AND is_active=0"
        if "is_deleted" in hcols:
            where += " AND is_deleted=0"

        sql = f"SELECT {', '.join(select_cols)} FROM history WHERE {where} ORDER BY id ASC"
        params: list[Any] = [cid]
        if hist_limit and hist_limit > 0:
            sql += " LIMIT ?"
            params.append(int(hist_limit))

        corpus: list[dict] = []
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        for row in rows:
            rd = dict(zip(select_cols, row))
            msg = hm._reconstruct_message_from_db(rd.get("role"), rd.get("content"), rd.get("meta_data"))
            msg["time"] = rd.get("timestamp") or ""

            for k in hm._HISTORY_DESIRED_COLUMNS.keys():
                if k in cols_set and rd.get(k) not in (None, ""):
                    msg[k] = rd.get(k)

            msg = hm._normalize_loaded_message(msg)
            corpus.append(msg)

        # memories
        mcols = self.table_cols("memories")
        has_is_deleted = "is_deleted" in mcols
        has_is_forgotten = "is_forgotten" in mcols

        mem_select = ["content", "priority", "type", "date_created"]
        if "participants" in mcols:
            mem_select.append("participants")
        if has_is_forgotten:
            mem_select.append("is_forgotten")

        mem_where = "character_id=?"
        if has_is_deleted:
            mem_where += " AND is_deleted=0"

        mem_sql = f"SELECT {', '.join(mem_select)} FROM memories WHERE {mem_where} ORDER BY id ASC"
        mem_params: list[Any] = [cid]
        if mem_limit and mem_limit > 0:
            mem_sql += " LIMIT ?"
            mem_params.append(int(mem_limit))

        mems: list[dict] = []
        conn2 = self.db.get_connection()
        try:
            cur2 = conn2.cursor()
            cur2.execute(mem_sql, tuple(mem_params))
            mem_rows = cur2.fetchall() or []
        finally:
            try:
                conn2.close()
            except Exception:
                pass

        for r in mem_rows:
            i = 0
            content = r[i]; i += 1
            priority = r[i] if i < len(r) else "Normal"; i += 1
            mtype = r[i] if i < len(r) else "fact"; i += 1
            date_created = r[i] if i < len(r) else ""; i += 1

            participants = None
            if "participants" in mcols:
                participants = r[i] if i < len(r) else None
                i += 1

            is_forgotten = 1
            if has_is_forgotten:
                is_forgotten = safe_int(r[i] if i < len(r) else 0, 0)

            d = {
                "content": content,
                "priority": priority,
                "type": mtype,
                "date_created": date_created,
                "is_forgotten": is_forgotten,
            }
            if participants is not None:
                d["participants"] = participants
            mems.append(d)

        return Scenario(character_id=cid, context=active, history=corpus, memories=mems)

    def index_missing(self, cid: str) -> int:
        rag = RAGManager(cid)
        return int(rag.index_all_missing(progress_callback=None) or 0)

    def missing_count(self, cid: str) -> int:
        hm = HistoryManager(character_name=cid, character_id=cid)
        return int(hm.get_missing_embeddings_count() or 0)

    # -------------------------
    # RAG search / preview
    # -------------------------
    def build_effective_query(self, cid: str, query: str, *, tail: int = 2) -> str:
        rag = RAGManager(cid)
        try:
            return rag._build_query_from_recent(query, tail=tail)  # private ok in tester
        except Exception:
            return str(query or "")

    def search(
        self,
        *,
        cid: str,
        query: str,
        limit: int,
        threshold: float,
        use_overrides: bool,
        overrides: dict[str, Any] | None,
    ) -> list[dict]:
        rag = RAGManager(cid)
        if use_overrides and overrides:
            with SettingsOverride(overrides):
                return rag.search_relevant(query=query, limit=int(limit), threshold=float(threshold))
        return rag.search_relevant(query=query, limit=int(limit), threshold=float(threshold))

    def build_injection_preview(self, results: list[dict]) -> str:
        """
        Превью блоков как в твоём process_rag():
        <relevant_memories>...</relevant_memories>
        <past_context>...</past_context>
        """
        def clip(s: Any, n: int = 700) -> str:
            t = str(s or "").strip()
            return (t[:n] + "…") if len(t) > n else t

        mem_lines: list[str] = []
        hist_lines: list[str] = []

        for r in results or []:
            if not isinstance(r, dict):
                continue
            src = r.get("source")
            if src == "memory":
                mem_lines.append(
                    f"- [{safe_float(r.get('score'), 0.0):.3f}] "
                    f"({r.get('type')}, prio={r.get('priority')}, date={r.get('date_created')}) "
                    f"{clip(r.get('content'))}"
                )
            elif src == "history":
                dt = r.get("date")
                sp = r.get("speaker") or ""
                tg = r.get("target") or ""
                meta = f"{sp}→{tg}" if (sp and tg) else (sp or (f"→{tg}" if tg else ""))
                meta_s = f" ({meta})" if meta else ""
                hist_lines.append(
                    f"- [{safe_float(r.get('score'), 0.0):.3f}] ({dt}){meta_s} {clip(r.get('content'))}"
                )

        blocks: list[str] = []
        if mem_lines:
            blocks.append("<relevant_memories>\n" + "\n".join(mem_lines) + "\n</relevant_memories>")
        if hist_lines:
            blocks.append("<past_context>\n" + "\n".join(hist_lines) + "\n</past_context>")

        return "\n\n".join(blocks)