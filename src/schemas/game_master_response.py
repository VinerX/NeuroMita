"""Structured action contract emitted by the hidden GameMaster."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.structured_response import _to_gemini_schema


class GameMasterAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["upsert_rule", "remove_rule", "clear_rules", "route", "narrate", "no_action"]
    target: str = Field(
        default="",
        description=(
            "Exact participant target from [PRESENT_PARTICIPANTS]. Copy target= verbatim; "
            "do not translate it and do not use the display-only name= value."
        ),
    )
    rule_id: str = ""
    key: str = ""
    instruction: str = ""
    lifetime: Literal["next_reply", "replies", "scene"] = "scene"
    replies: int = Field(default=0, ge=0, le=24)
    reason: str = ""


class GameMasterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actions: list[GameMasterAction] = Field(default_factory=list, max_length=16)

    @classmethod
    def openai_response_format(cls, **_kwargs) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "game_master_response",
                "strict": False,
                "schema": cls.model_json_schema(),
            },
        }

    @classmethod
    def gemini_schema_dict(cls, **_kwargs) -> dict:
        return _to_gemini_schema(cls.model_json_schema())