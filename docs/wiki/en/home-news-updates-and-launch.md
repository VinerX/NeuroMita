# Home, News, Updates, and Launch

[Wiki Home](./index.md)

## Purpose

The `Home` page is the operational entry point for the packaged app. It is where users see installation state, update state, launch actions, and recent release news.

## What You Can Do Here

- Install the Unity/game-side package when it is missing.
- Update the Python/backend side, the Unity side, or both.
- Launch the installed Unity/game-side executable.
- Read the latest release feed and open the full news page.

## Status Cards

The main status cards summarize whether the backend and Unity parts are installed, outdated, or ready to launch.

- Backend status is about the Python-side application content.
- Unity status is about the installable game-side package.
- If updates are available, the page can expose checkboxes so users choose which part to update.

## Primary Action Button

The primary button changes meaning depending on state:

- `Install` when the target component is not present.
- `Update` when one or more selected updates are available.
- `Restart` when a Python-side update has been installed and the app needs a restart.
- `Play` when everything is installed and no selected updates remain.

## News and Release Feed

The home page also surfaces release notes. If the remote feed is unavailable, the app falls back to a local state instead of blocking the rest of the UI.

## When to Use the News Page

Use the dedicated `News` page when you want the fuller release stream instead of the short dashboard summary.

## Related Pages

- Basic app orientation: [Getting Started](./getting-started.md)
- Full configuration: [Chat, Characters, and Prompt Flow](./chat-and-characters.md)
- Local AI component maintenance: [Memory, Data, AI Hub, and Debugging](./memory-data-ai-hub-and-debugging.md#ai-hub-and-local-components)
