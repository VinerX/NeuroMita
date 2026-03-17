from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RequestPolicy:
    template_name_override: Optional[str] = None

    use_history_in_prompt: bool = True
    write_to_history: bool = True

    allow_voiceover: bool = True
    allow_streaming: bool = True
    echo_to_ui: bool = True

    use_pending_sysinfo: bool = True

    system_input_role: str = "system"  # "system" | "event"
    react_level: Optional[int] = None  # 1 | 2 | None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_name_override": self.template_name_override,
            "use_history_in_prompt": bool(self.use_history_in_prompt),
            "write_to_history": bool(self.write_to_history),
            "allow_voiceover": bool(self.allow_voiceover),
            "allow_streaming": bool(self.allow_streaming),
            "echo_to_ui": bool(self.echo_to_ui),
            "use_pending_sysinfo": bool(self.use_pending_sysinfo),
            "system_input_role": str(self.system_input_role or "system"),
            "react_level": self.react_level,
        }

    @staticmethod
    def from_dict(d: Any) -> "RequestPolicy":
        if not isinstance(d, dict):
            return RequestPolicy()

        rl = d.get("react_level", None)
        try:
            rl = int(rl) if isinstance(rl, (int, float, str)) and str(rl).strip() != "" else None
        except Exception:
            rl = None

        return RequestPolicy(
            template_name_override=d.get("template_name_override"),
            use_history_in_prompt=bool(d.get("use_history_in_prompt", True)),
            write_to_history=bool(d.get("write_to_history", True)),
            allow_voiceover=bool(d.get("allow_voiceover", True)),
            allow_streaming=bool(d.get("allow_streaming", True)),
            echo_to_ui=bool(d.get("echo_to_ui", True)),
            use_pending_sysinfo=bool(d.get("use_pending_sysinfo", True)),
            system_input_role=str(d.get("system_input_role") or "system"),
            react_level=rl,
        )


def _parse_react_level(value: Any) -> int:
    if value is None:
        return 1

    if isinstance(value, (int, float)):
        return 2 if int(value) == 2 else 1

    s = str(value).strip().lower()
    if not s:
        return 1

    # Unity enum ToString(): "Silent" / "Answer"
    if s in ("answer", "l2", "level2", "2"):
        return 2
    if s in ("silent", "l1", "level1", "1"):
        return 1

    return 1


def resolve_policy(*, model_event_type: str, react_level: Any = None) -> RequestPolicy:
    et = str(model_event_type or "").strip().lower()

    if et == "react":
        lvl = _parse_react_level(react_level)

        if lvl == 2:
            return RequestPolicy(
                react_level=2,
                template_name_override="main_template.txt",
                use_history_in_prompt=True,
                write_to_history=True,
                allow_voiceover=True,
                allow_streaming=True,
                echo_to_ui=True,
                use_pending_sysinfo=True,
                system_input_role="event",
            )

        return RequestPolicy(
            react_level=1,
            template_name_override="react_template.txt",
            use_history_in_prompt=False,
            write_to_history=False,
            allow_voiceover=False,
            allow_streaming=False,
            echo_to_ui=False,
            use_pending_sysinfo=False,
            system_input_role="system",
        )

    return RequestPolicy(
        template_name_override=None,
        use_history_in_prompt=True,
        write_to_history=True,
        allow_voiceover=True,
        allow_streaming=True,
        echo_to_ui=True,
        use_pending_sysinfo=True,
        system_input_role="system",
        react_level=None,
    )