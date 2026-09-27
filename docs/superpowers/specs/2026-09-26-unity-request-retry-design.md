# Retry failed Unity requests from Sandbox

## Goal

When a Unity-originated player message fails during model generation, keep the
message visible in Sandbox and let the user retry it later. A retry must create
a new task for the currently connected Unity client and deliver the generated
answer back through the normal game task-update path. Pending requests must
survive application restarts.

## Current behavior

- `CreateTaskAction` echoes player messages to the desktop chat and separately
  creates an in-memory task for the Unity client.
- A failed generation updates that task to `FAILED_ON_GENERATION` and emits a
  model failure event keyed to the incoming message ID.
- The ordinary chat retry cache only retains manually submitted desktop
  requests in memory; Unity requests are not eligible for it.
- Task IDs and connection IDs are transient. A retry after reconnect cannot
  reuse the old task or client ID.

## Proposed behavior

1. Persist a Unity-originated player request before generation begins,
   including the message identity, character, text, relevant prompt/context,
   policy, dialogue/game state, participants, and any images needed to reproduce
   the original request.
2. Track explicit states: `generating`, `needs_generation`,
   `generated_pending_voiceover`, `generated_pending_delivery`, and
   `delivery_retrying`. On startup, recover only records from an earlier
   process session. Interrupted generation becomes `needs_generation`; an
   already generated result remains available for delivery without another LLM
   call.
3. On explicit retry, require an active game connection, create a fresh task
   bound to the current primary game client, and submit the preserved request
   through the existing generation path. Do not reuse the old task UID or
   connection ID.
4. Keep the pending record while the retry is running or fails. Persist the
   complete generated task result before attempting transport. If socket
   delivery fails after generation, retry by creating a fresh Unity task with
   the saved result; do not invoke the model, rewrite history, or reapply
   structured side effects. Remove the record after the task update is written
   and drained successfully by the socket.
5. Do not automatically replay requests on startup or reconnect. Retrying is
   user initiated to avoid unexpected duplicate game actions.

## Boundaries and safety

- The retry record is an operational outbox, separate from conversational
  history and RAG. A failed attempt must not be inserted into active history
  merely to make it visible.
- Preserve request context needed for equivalent generation, but exclude
  transient transport identifiers from retry identity. A new task gets a new
  task UID and current client ID.
- Retried requests must keep the original event policy and semantic context so
  the response follows existing Unity delivery rules.
- Store one versioned JSON outbox per character under that character's history
  directory, following the existing reminder storage convention. Write through
  a temporary file in the same directory, flush it, then atomically replace the
  outbox file.
- Retain requests for 30 days, with at most 100 records per character and a
  64 MiB total serialized outbox limit. Prune expired records first. If a new
  record would exceed either cap, keep generation running without evicting a
  still-valid request. If the user later retries that message, state that the
  original request context could not be retained.
- Preserve image bytes as base64 only within those same caps. If an image makes
  the outbox exceed its limit, the request remains visible but cannot be retried
  with a misleading partial context.
- Persistence writes must be atomic and tolerate a truncated/corrupt store by
  logging the issue without preventing application startup.

## Components

- A small persistent pending-request store under the per-character history
  directory, with add/update/remove/load operations and bounded retention.
- The game task creation path records eligible Unity player requests before
  generation begins and finalizes/removes them on success.
- The Sandbox chat presentation restores pending records and exposes retry
  actions keyed by the stable incoming message ID.
- Retry coordination resolves the current primary Unity connection and creates
  a new task before dispatching the preserved request through the existing
  `ChatController` generation path.

## Completion criteria

- A failed Unity player message remains visible with a retry affordance.
- Retrying while Unity is connected creates a distinct task and returns its
  successful result to Unity.
- A failed retry remains available for another explicit attempt.
- A pending request survives application restart and is restored in Sandbox.
- Successful completion removes the pending retry record.
- Manual desktop chat retry behavior remains unchanged.

## Restore and interaction details

- Restore queue records into the Sandbox conversation surface when it loads,
  ordered by original receipt time and keyed by the stable incoming message ID.
  Do not insert these diagnostic records into model history or RAG.
- If the same message is already present in the live view, update its retry
  state instead of appending a duplicate.
- If no game client is connected when the user retries, keep the request and
  show a reconnect-required message. A later click creates a fresh task for the
  then-current primary game client.
- After process restart, records left in the in-progress state return to the
  retryable state. The user must explicitly start the attempt again.
- A `send_json` success means the local socket write drained; the current
  protocol has no Unity acknowledgement. This supports retry on observed socket
  failure, but cannot guarantee exactly-once application by Unity.
