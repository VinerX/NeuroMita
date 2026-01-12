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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_name_override": self.template_name_override,
            "use_history_in_prompt": bool(self.use_history_in_prompt),
            "write_to_history": bool(self.write_to_history),
            "allow_voiceover": bool(self.allow_voiceover),
            "allow_streaming": bool(self.allow_streaming),
            "echo_to_ui": bool(self.echo_to_ui),
            "use_pending_sysinfo": bool(self.use_pending_sysinfo),
        }

    @staticmethod
    def from_dict(d: Any) -> "RequestPolicy":
        if not isinstance(d, dict):
            return RequestPolicy()

        return RequestPolicy(
            template_name_override=d.get("template_name_override"),
            use_history_in_prompt=bool(d.get("use_history_in_prompt", True)),
            write_to_history=bool(d.get("write_to_history", True)),
            allow_voiceover=bool(d.get("allow_voiceover", True)),
            allow_streaming=bool(d.get("allow_streaming", True)),
            echo_to_ui=bool(d.get("echo_to_ui", True)),
            use_pending_sysinfo=bool(d.get("use_pending_sysinfo", True)),
        )


def resolve_policy(*, model_event_type: str) -> RequestPolicy:
    """
    Stage 1: keep legacy behavior.
    - model_event_type == 'react' => silent, no history, no voice, no UI echo, no pending_sysinfo.
    - otherwise => normal chat-like behavior.
    """
    et = str(model_event_type or "").strip().lower()
    if et == "react":
        return RequestPolicy(
            template_name_override="react_template.txt",
            use_history_in_prompt=False,
            write_to_history=False,
            allow_voiceover=False,
            allow_streaming=False,
            echo_to_ui=False,
            use_pending_sysinfo=False,
        )

    return RequestPolicy(
        template_name_override=None,
        use_history_in_prompt=True,
        write_to_history=True,
        allow_voiceover=True,
        allow_streaming=True,
        echo_to_ui=True,
        use_pending_sysinfo=True,
    )