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
- Available updates are never selected automatically. The `NEW` badge is informational; only the checkbox opts a component into the next operation.

## Primary Action Button

The primary button changes meaning depending on state:

- `Install Unity` only when missing Unity was explicitly selected.
- `Install components (2)` when installing Unity and updating Python were both selected.
- `Update` when one or more updates were explicitly selected.
- `Restart` when a Python-side update has been installed and the app needs a restart.
- `Play` when everything is installed and no selected updates remain.
- `Unity is required to play` when Unity is missing and its install checkbox is not selected.
- `Unity is running — close` while the launcher-owned or recovered Unity process is alive.

The right side of the split button opens contextual maintenance actions while idle. During cancellable download or extraction stages it becomes a direct cancel action; verification and commit stages disable cancellation because interrupting them would be misleading.

## Recoverable Installation

Both components download through a resumable `.part` cache, are checked against the release size and SHA-256 digest when available, and are extracted outside the live install directory. Each explicitly authorized operation has a durable journal. The staged tree receives a per-file manifest, so a launcher restart can verify and reuse it instead of downloading again.

Unity activation uses a same-volume directory swap with a temporary backup. If activation or post-activation verification fails, the previous directory is restored. Python uses a durable external stage that remains intact until its overlay or full application completes, allowing an interrupted write to be repeated after restart. Interrupted authorized operations are recovered on the next launcher start; completed archives, staging directories, and rollback backups are removed only after successful application and verification.

## News and Release Feed

The home page also surfaces release notes. If the remote feed is unavailable, the app falls back to a local state instead of blocking the rest of the UI.

## When to Use the News Page

Use the dedicated `News` page when you want the fuller release stream instead of the short dashboard summary.

## Related Pages

- Basic app orientation: [Getting Started](./getting-started.md)
- Full configuration: [Chat, Characters, and Prompt Flow](./chat-and-characters.md)
- Local AI component maintenance: [Memory, Data, AI Hub, and Debugging](./memory-data-ai-hub-and-debugging.md#ai-hub-and-local-components)
