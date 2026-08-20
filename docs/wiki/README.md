# NeuroMita User Wiki

This folder contains the user-facing application wiki in a translation-ready layout.

## Structure

- `en/` - English source pages
- `ru/` - Russian translation
- future locale folders such as `de/`, `fr/`, `ja/` can mirror the same slugs

## Rules

- Keep the page slugs stable so internal links survive translation.
- Link pages relatively, for example `./chat-and-characters.md`.
- Prefer user-facing explanations over implementation details.
- When a feature exists in multiple places in the UI, describe the primary user path first.

Start here: [Russian index](./ru/index.md) or [English index](./en/index.md)
