# src/tools/dialects/registry.py
from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Optional

from main_logger import logger
from .base import ToolDialect


class ToolDialectRegistry:
    """
    Автодискавери диалектов в tools.dialects.*:
      - модуль должен экспортировать Dialect (класс) или create_dialect() (фабрика)
    """

    def __init__(self, auto_discover: bool = True):
        self._dialects: Dict[str, ToolDialect] = {}
        self._aliases: Dict[str, str] = {}

        if auto_discover:
            self.discover()

    def discover(self) -> None:
        try:
            pkg = importlib.import_module("tools.dialects")
        except Exception as e:
            logger.error(f"[ToolDialectRegistry] Cannot import tools.dialects: {e}", exc_info=True)
            return

        try:
            for mod in pkgutil.iter_modules(pkg.__path__):
                name = mod.name
                if name in ("base", "registry", "__init__"):
                    continue
                full = f"tools.dialects.{name}"
                try:
                    module = importlib.import_module(full)
                except Exception as e:
                    logger.warning(f"[ToolDialectRegistry] Failed to import {full}: {e}")
                    continue

                dialect: Optional[ToolDialect] = None

                create_fn = getattr(module, "create_dialect", None)
                if callable(create_fn):
                    try:
                        dialect = create_fn()
                    except Exception as e:
                        logger.warning(f"[ToolDialectRegistry] create_dialect() failed in {full}: {e}")
                        continue
                else:
                    DialectCls = getattr(module, "Dialect", None)
                    if DialectCls:
                        try:
                            dialect = DialectCls()
                        except Exception as e:
                            logger.warning(f"[ToolDialectRegistry] Dialect() init failed in {full}: {e}")
                            continue

                if dialect:
                    self.register(dialect)

        except Exception as e:
            logger.error(f"[ToolDialectRegistry] Discovery failed: {e}", exc_info=True)

    def register(self, dialect: ToolDialect) -> None:
        did = (dialect.id or "").strip()
        if not did:
            raise ValueError("Dialect id cannot be empty")
        self._dialects[did] = dialect

    def add_alias(self, alias: str, target_id: str) -> None:
        alias = (alias or "").strip()
        target_id = (target_id or "").strip()
        if not alias or not target_id:
            return
        self._aliases[alias] = target_id

    def get(self, dialect_id_or_alias: str) -> Optional[ToolDialect]:
        key = (dialect_id_or_alias or "").strip()
        if not key:
            return None
        if key in self._dialects:
            return self._dialects[key]
        if key in self._aliases:
            return self._dialects.get(self._aliases[key])
        return None

    def list_ids(self) -> List[str]:
        return sorted(self._dialects.keys())

    def list_meta(self) -> List[dict]:
        out = []
        for did in self.list_ids():
            d = self._dialects[did]
            out.append({"id": d.id, "title": getattr(d, "title", d.id)})
        return out