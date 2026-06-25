# Chat, Characters, and Prompt Flow

[Wiki Home](./index.md)

## Text Generation and Provider Setup

The app supports several ways to generate text responses:

- direct API providers
- proxy-style OpenAI-compatible endpoints
- provider presets
- local or semi-local workflows where supported

Users typically configure this in [API settings](app:settings/api), then chat from the main interface. If the preset list is empty, click the **"Click to create a preset"** prompt (or the **+** button next to it) to add your first one.

## What a Character Controls

A character is more than a name. It usually defines:

- prompt set and personality
- response style
- memory behavior
- optional voice identity
- optional special logic, commands, or structured outputs

## Prompt and Character-Related Areas in Settings

- [API settings](app:settings/api): provider, endpoint, key, model, preset selection
- [Character settings](app:settings/characters): active profile, character-specific logic, prompt assets
- [Model interaction settings](app:settings/models): response behavior, waiting, and related controls
- [Language settings](app:settings/language): interface language

## Chat Features

From the user side, the chat UI supports:

- normal text messages
- assistant replies
- regeneration of the latest reply
- regeneration from an earlier message
- editing or deleting messages
- copying selected text or the full message
- optional structured response panels
- optional image bubbles
- optional request and response context inspection

## Message Context and History

Every chat turn can involve more than visible text:

- hidden prompt context
- retrieved RAG context
- image descriptions
- provider settings and token usage
- optional structured machine-readable data

That is why the context viewer exists: it shows what the model actually saw and what it returned.

## Character and Game Connection Behavior

Depending on configuration, the app can act as a standalone chat system or as a bridge between the player, the AI character, and the game/mod runtime.

## Related Pages

- Onboarding: [Getting Started](./getting-started.md)
- Voice and capture features: [Voice, Microphone, Camera, and Screen Features](./voice-microphone-camera-and-screen.md)
- Memory and RAG: [Memory, Data, AI Hub, and Debugging](./memory-data-ai-hub-and-debugging.md#rag-memory-and-knowledge-graph)
