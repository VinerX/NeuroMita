# Memory, Data, AI Hub, and Debugging

[Wiki Home](./index.md)

## RAG, Memory, and Knowledge Graph

NeuroMita can augment replies with stored context rather than relying only on the live chat window.

Main user-facing memory systems include:

- message history
- memories
- RAG retrieval
- optional knowledge graph extraction
- memory profiles that trade off depth, speed, and context size

Most of this lives in `Settings > RAG / memory`.

For a deeper RAG explanation, also see the separate document: [RAG Guide](../../RAG_Guide.md)

## What Users Can Tune

- whether RAG is enabled
- which sources are searched
- result limits and thresholds
- retrieval combination modes
- ranking weights
- graph search participation
- cross-encoder reranking
- detailed RAG logging

## Data Collection

The app can locally store request/response samples for later analysis or fine-tuning workflows.

This area covers:

- enabling or disabling finetune data collection
- keeping a bounded or unlimited sample set
- exporting collected data
- rating assistant replies

## AI Hub and Local Components

The `AI Hub` is the maintenance surface for installable local AI assets and dependencies. From a user perspective, this is where you manage model downloads, removals, and related component state.

This is especially relevant for:

- local voice models
- local embedding or reranker models
- system dependencies needed by specific AI features

## Logs, Sandbox, and Request Context

There are three main diagnostic surfaces:

- `Logs`: the live tail of `NeuroMitaLogs.log`
- `Sandbox`: status chips, quick toggles, memory stats, and debug shortcuts
- `Request/response context viewer`: the per-turn inspection dialog for what the model received and returned

Use the context viewer when you need to answer questions like:

- why did the model answer this way
- what RAG snippets were injected
- which provider and model were used
- whether a response was cleaned or transformed

## Developer-Oriented Pages

The `Developer` page is for advanced maintenance and contributor workflows. Regular users usually do not need it for everyday chatting, but it is valuable when verifying install state, diagnostics, or internal tooling.

## Related Pages

- General workflow: [Getting Started](./getting-started.md)
- Provider and character setup: [Chat, Characters, and Prompt Flow](./chat-and-characters.md)
- Voice and capture systems: [Voice, Microphone, Camera, and Screen Features](./voice-microphone-camera-and-screen.md)
