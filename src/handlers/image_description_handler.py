"""
Non-native image description handler.

When IMAGE_DESCRIPTION_ENABLED=True and the main model does not support vision,
this handler calls a separate vision-capable provider to describe images,
returning plain-text descriptions that the main model can understand.

Detail level is controlled by IMAGE_DESCRIPTION_DETAIL setting:
  "brief"    — 1 sentence, key subject only
  "normal"   — 2-3 sentences, main elements + context  (default)
  "detailed" — thorough: objects, people, text, colors, mood
"""

from __future__ import annotations
from core.error_utils import format_exception

import base64
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ── Prompts per detail level ────────────────────────────────────────────────
# These are also used by prompt_controller.py for the inline-description
# instruction, so import them from here to keep one source of truth.

DETAIL_PROMPTS: dict[str, str] = {
    "brief": (
        "Describe this image in a single sentence. "
        "Mention only the most important subject or action visible."
    ),
    "normal": (
        "Describe this image in 2-3 sentences. "
        "Cover the main subjects, their actions, and the overall setting. "
        "Do not speculate beyond what is shown."
    ),
    "detailed": (
        "Describe this image thoroughly in 4-6 sentences. "
        "Include: all visible objects and people, their expressions and actions, "
        "colors and lighting, any readable text, the background, and the overall mood. "
        "Be precise and do not speculate."
    ),
}

DETAIL_LEVELS = list(DETAIL_PROMPTS.keys())   # ["brief", "normal", "detailed"]
DEFAULT_DETAIL = "normal"

SYSTEM_PREAMBLE = (
    "You are an image description assistant helping a text-only AI understand visual content. "
)


def get_description_prompt(detail: str) -> str:
    """Return the full system prompt for the given detail level."""
    level = str(detail or DEFAULT_DETAIL).strip().lower()
    body = DETAIL_PROMPTS.get(level, DETAIL_PROMPTS[DEFAULT_DETAIL])
    return SYSTEM_PREAMBLE + body


def get_inline_instruction(detail: str) -> str:
    """
    Return the system-message instruction injected into the main model's prompt
    when IMAGE_INLINE_DESCRIPTION is enabled (non-structured / plain text output).
    """
    level = str(detail or DEFAULT_DETAIL).strip().lower()
    body = DETAIL_PROMPTS.get(level, DETAIL_PROMPTS[DEFAULT_DETAIL])
    return (
        "The user has sent one or more images. Before your response, output a block:\n"
        "<image_description>\n"
        f"[{body}]\n"
        "</image_description>\n"
        "This block will be hidden from the user and stored for memory only."
    )


def get_structured_inline_instruction(detail: str) -> str:
    """
    Return the system-message instruction for IMAGE_INLINE_DESCRIPTION
    when the model uses structured (JSON schema) output.

    Instead of XML tags (which break JSON), the model fills the dedicated
    `image_description` field in the JSON schema.
    """
    level = str(detail or DEFAULT_DETAIL).strip().lower()
    body = DETAIL_PROMPTS.get(level, DETAIL_PROMPTS[DEFAULT_DETAIL])
    return (
        "The user has sent one or more images. "
        f"Describe what you see in the `image_description` field of your JSON response ({body}). "
        "This field is stored in memory and never shown to the player. "
        "Then compose your segments as usual."
    )


# ── Handler class ────────────────────────────────────────────────────────────

class ImageDescriptionHandler:
    """Calls a vision provider to convert images → text descriptions."""

    def __init__(self, model: Any, settings: Any) -> None:
        self.model = model
        self.settings = settings

    @staticmethod
    def _is_current_label(label: str) -> bool:
        """True when the label means 'use the currently active preset'."""
        return label in ("", "Current", "Текущий")

    def _resolve_preset_id(self) -> Optional[int]:
        provider_label = str(self.settings.get("IMAGE_DESCRIPTION_PROVIDER", "") or "").strip()
        if self._is_current_label(provider_label):
            return None
        try:
            return int(provider_label)
        except (ValueError, TypeError):
            pass
        try:
            from managers.api_preset_resolver import ApiPresetResolver
            resolver = ApiPresetResolver(settings=self.settings, event_bus=None)
            return resolver.resolve_preset_id_by_name(provider_label)
        except Exception:
            return None

    def describe_sequence(self, image_data: List[bytes], context_hint: str = "") -> str:
        """
        Describe multiple images as a single scene/sequence in one API call.
        All images are sent together so the model can reason about continuity.
        Returns a single description string.

        context_hint: optional hint prepended to the user message so the vision
        model knows the source/role of the images (e.g. camera POV).
        """
        if not image_data:
            return ""

        detail = str(self.settings.get("IMAGE_DESCRIPTION_DETAIL", DEFAULT_DETAIL) or DEFAULT_DETAIL)
        system_prompt = get_description_prompt(detail)
        preset_id = self._resolve_preset_id()

        seq_text = f"These are {len(image_data)} sequential frames from a scene. Describe what is happening across the sequence."
        if context_hint:
            seq_text = f"{context_hint}\n\n{seq_text}"

        content_parts: list = [
            {"type": "text", "text": seq_text}
        ]
        for img in image_data:
            if isinstance(img, bytes):
                b64 = base64.b64encode(img).decode("utf-8")
            else:
                b64 = str(img).split(",", 1)[-1]
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_parts},
        ]
        try:
            result = self.model.generate(messages, stream_callback=None, preset_id=preset_id)
            return str(result).strip() if result and str(result).strip() else "[Scene description unavailable]"
        except Exception as exc:
            logger.warning(f"[ImageDescriptionHandler] Failed to describe sequence of {len(image_data)} images: {format_exception(exc)}")
            return "[Scene description unavailable]"

    def describe(self, image_data: List[bytes], context_hint: str = "") -> List[str]:
        """
        Describe each image using a vision provider.
        Returns a list of text descriptions (one per image).
        Falls back to placeholder if a call fails.

        context_hint: optional hint prepended to the user message so the vision
        model knows the source/role of the images (e.g. camera POV).
        """
        if not image_data:
            return []

        detail = str(self.settings.get("IMAGE_DESCRIPTION_DETAIL", DEFAULT_DETAIL) or DEFAULT_DETAIL)
        system_prompt = get_description_prompt(detail)
        preset_id = self._resolve_preset_id()
        descriptions: List[str] = []

        user_text = "Please describe this image."
        if context_hint:
            user_text = f"{context_hint}\n\nPlease describe this image."

        for i, img in enumerate(image_data):
            try:
                if isinstance(img, bytes):
                    b64 = base64.b64encode(img).decode("utf-8")
                else:
                    b64 = str(img).split(",", 1)[-1]

                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    },
                ]

                result = self.model.generate(messages, stream_callback=None, preset_id=preset_id)
                if result and str(result).strip():
                    descriptions.append(str(result).strip())
                else:
                    descriptions.append(f"[Image {i + 1}: description unavailable]")

            except Exception as exc:
                logger.warning(f"[ImageDescriptionHandler] Failed to describe image {i + 1}: {format_exception(exc)}")
                descriptions.append(f"[Image {i + 1}: description unavailable]")

        return descriptions
