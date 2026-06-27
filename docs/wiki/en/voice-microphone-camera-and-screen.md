# Voice, Microphone, Camera, and Screen Features

[Wiki Home](./index.md)

## Voice Output

NeuroMita can speak responses instead of showing text only.

Main voice modes include:

- local voice models
- Telegram-based voice workflows where configured
- selectable voice model pipelines depending on installed assets

Users manage this under `Settings > Voice`.

## Microphone Input

Microphone support lets the app capture speech and convert it into text input for the chat flow.

Typical controls include:

- recognizer choice
- microphone device selection
- recognition start or stop behavior
- glossary or speech-processing helpers

Users manage this under `Settings > Microphone`.

## Screen Capture and Image Analysis

The app can capture the screen, attach frames to requests, and analyze images. This is useful when the AI should react to the game view or the desktop state.

Typical options include:

- enabling screen capture
- capture interval and quality
- frame history and transfer limits
- excluding the GUI window from capture
- enabling image request workflows

## Camera Capture

Camera capture is separate from screen capture. It can send webcam frames or other camera sources into the same multimodal flow.

Typical options include:

- device selection
- capture interval
- compression and frame size
- history and transfer limits

## When to Use the Sandbox

The `Sandbox` page is useful for live control because it shows current voice, microphone, and RAG state and provides quick toggles without opening every settings section.

## Related Pages

- Chat behavior: [Chat, Characters, and Prompt Flow](./chat-and-characters.md)
- Memory and debugging: [Memory, Data, AI Hub, and Debugging](./memory-data-ai-hub-and-debugging.md)
