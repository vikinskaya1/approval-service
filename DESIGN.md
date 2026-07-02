# DESIGN

## Data model

**approval_requests** — the aggregate root.
- `id` (uuid), `workspace_id`
- `source_type` (`publication|scenario|edit|external`), `source_id` — opaque
  reference to the thing being approved; owned by other services
- `title`, `description`
- `reviewer_user_ids` (JSON list of opaque user ids)
- `status`: `pending → {approved | rejected | cancelled}`. The three
  non-pending states are final — once set, the row can never move again
  (enforced in `crud._apply_decision`, not just in the API layer)
- `created_by`, `created_at`, `updated_at`
- `decided_by`, `decided_at`, `decision_comment` (approve), `decision_reason`
  (reject/cancel)
- `version` — bumped on every decision; not currently used for
  optimistic-concurrency checks from the client, but present so that can be
  added later without a migration

**audit_logs** — one immutable row per state change (`created`, `approved`,
`rejected`, `cancelled`), with `actor_user_id` and a small `details` JSON
blob (comment/reason only — never raw provider data). This is the "who did
what" trail the task asks for; it's append-only and never updated in place.

**outbox_events** — one row per state change, written in the same
transaction as the change itself (transactional outbox pattern). See
"Events / integration" below.

**idempotency_records** — see "Idempotency".

All four tables carry `workspace_id` directly (denormalized, not inferred by
joining through `approval_requests`), so every query that must be
workspace-scoped can filter on an indexed column without a join, including
the audit and event tables.

## Service boundaries

This service owns *only* the approval workflow and its own audit/event
trail. It does not:
- store or fetch the actual publication/scenario/edit content — those stay
  as opaque `sourceType`/`sourceId` pairs, resolved by whichever service
  owns them;
- store user or workspace records — `created_by`, `decided_by`,
  `reviewer_user_ids`, `workspace_id` are all opaque foreign ids from other
  systems, never joined against locally;
- authenticate users — see the auth stub in `app/auth.py` and `README.md`.
  In production this would be replaced by a dependency that verifies a real
  token against an auth service/gateway, but the shape it produces
  (`AuthContext(user_id, workspace_id, scopes)`) is exactly what the rest of
  the code depends on, so swapping it is a one-file change.

Workspace isolation is enforced at two levels: every query filters
`workspace_id`, *and* `get_auth_context` rejects any request where the URL's
`workspace_id` doesn't match the caller's own `X-Workspace-Id` — so even a
bug that forgot a `WHERE workspace_id = ...` clause somewhere would still be
caught by the fact that a token for `ws_1` can't even address `ws_2`'s URLs.

## Handling repeated requests (idempotency)

Every state-changing endpoint requires an `Idempotency-Key` header, scoped
per `(workspace_id, endpoint, idempotency_key)` — where "endpoint" for
`approve`/`reject`/`cancel` includes the target `request_id`, so the same
key value can be reused safely for a different request without colliding.

Flow, in `app/idempotency.py`:
1. Look up an existing record for the scope.
2. If found and the stored request hash matches the incoming body: replay
   the stored `(status_code, body)` — no business logic re-runs, no
   duplicate row, no duplicate audit/event entry.
3. If found but the hash differs: `409` — the same key was reused for a
   materially different request, which is almost certainly a client bug.
4. If not found: run the actual handler, then persist the result under that
   key.

**Known trade-off:** the business-change commit (in `crud.py`) and the
idempotency-record commit (in `idempotency.py`) are two separate
transactions, not one. If the process crashes between them, a retry with
the same key would re-run the handler once more. For `create`, `approve`,
`reject`, `cancel` this is self-limiting rather than silently duplicating:
`create` is the only one that could theoretically insert a second row in
that narrow window (crash between committing the insert and committing the
idempotency record). A stricter version would move the idempotency insert
into the same transaction as the business change (or reserve the key
row *before* running the handler, inside one transaction, using a `SELECT
... FOR UPDATE`-style lock). Left out here to keep `crud.py` free of
idempotency concerns and the diff small enough to review in a test task.

## Events / integration

`outbox_events` is written in the *same* DB transaction as the state change
it describes (`create_approval_request` / `_apply_decision` both `db.add()`
the event row before the single `db.commit()`), which is what makes it
usable as a transactional outbox: the event can never be "lost" relative to
the state it describes, and it can never be published for a change that got
rolled back.

This service does not publish to a broker itself — that's deliberately left
to a separate worker/process that polls `outbox_events WHERE published =
false`, forwards each row to whatever bus the rest of the system uses
(Kafka, SQS, etc.), and marks it published. That keeps this service's
runtime dependencies limited to its own database.

Event types emitted: `approval_request.created`, `approval_request.approved`,
`approval_request.rejected`, `approval_request.cancelled`. Payloads
(`app/events.py`) only ever contain the same opaque ids and status fields
already visible through the API — no secrets, tokens, emails, storage keys,
signed URLs, provider URLs, or raw provider payloads exist anywhere in this
service's data model, so there's nothing sensitive to accidentally leak
through an event, a log line, or an error response. The global exception
handler in `app/main.py` also makes sure an unexpected internal error
returns a generic message rather than a stack trace or exception args that
might embed a connection string.

## Known compromises / things a production version would add

- **Idempotency isn't fully transactional** with the business change (see
  above).
- **No pagination cursor** — `limit`/`offset` only; fine at this scale, but
  `offset` pagination degrades on very large tables.
- **No rate limiting / request size limits** — assumed to be handled by a
  gateway in front of this service.
- **`version` column is unused by clients today** — present for a future
  optimistic-concurrency check (e.g. `If-Match`) if two reviewers race to
  decide the same request; right now the DB-level "already final → 409"
  check is what actually prevents a double-decision, which is sufficient
  for the stated requirement but doesn't detect a race between two
  *simultaneous* first decisions as cleanly as a version check would.
- **Outbox publisher is out of scope** — this service writes the outbox
  table; draining it to a real broker is a separate component by design.
