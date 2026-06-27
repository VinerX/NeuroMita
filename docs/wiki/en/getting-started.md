# Getting Started

[Wiki Home](./index.md)

## What NeuroMita Is

NeuroMita is a desktop companion app that powers AI-driven characters, connects them to the game/mod environment, and lets you combine text generation, memory, voice, microphone input, screen or camera analysis, and local AI components.

## First Launch Checklist

You don't need any prior experience with AI providers or APIs — follow these in order. Gold links open the exact screen in the app.

1. Open the app and review the in-app guide if you want a short onboarding flow.
2. Open [API settings](app:settings/api) and add a provider preset (the empty list shows a **"Click to create a preset"** prompt, or use the **+** button). Paste your API key and pick a model. See [provider setup](./chat-and-characters.md#text-generation-and-provider-setup) if you're unsure which provider to choose.
3. Open [Characters](app:settings/characters) and choose the character / prompt set you want to talk to.
4. Optional: enable [voice output](app:settings/voice), [microphone input](app:settings/microphone), [RAG memory](app:settings/models?section=RAG), or [screen/camera capture](app:settings/screen).
5. Return to the main chat ([Sandbox](app:sandbox)) and send a first message.

## Main Areas of the App

- [Home](app:home): install, update, launch, and release feed.
- [Settings](app:settings): full configuration.
- [Sandbox](app:sandbox): live status, quick toggles, diagnostics.
- [Logs](app:logs): real-time log tail.
- [Developer](app:developer): advanced tools and contributor workflows.

## Core Usage Loop

1. You send text, optionally with images or live capture.
2. The app builds a prompt for the active character and provider.
3. Optional systems such as RAG, graph memory, tools, and image descriptions enrich the request.
4. The provider returns a response.
5. The response is shown in chat, can be stored in history, and can optionally trigger voice output.

## Related Pages

- Launcher behavior: [Home, News, Updates, and Launch](./home-news-updates-and-launch.md)
- Provider and character setup: [Chat, Characters, and Prompt Flow](./chat-and-characters.md)
- Media features: [Voice, Microphone, Camera, and Screen Features](./voice-microphone-camera-and-screen.md)
- Memory and debugging: [Memory, Data, AI Hub, and Debugging](./memory-data-ai-hub-and-debugging.md)
