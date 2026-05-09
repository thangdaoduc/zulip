# Favorites for Channels and Direct Messages — Design

**Date:** 2026-05-09
**Status:** Approved for implementation
**Scope:** Backend + web frontend (mobile/terminal clients out of scope)

## 1. Goal

Let a user mark a subscribed channel or a 1-1 direct message conversation as a "favorite" so it surfaces in a dedicated section at the top of the left sidebar. Favorites are per-user, sync across the user's sessions via the event system, and survive client restart.

Group DMs (3+ participants) and channels the user has not subscribed to are out of scope for the initial release.

## 2. Non-goals

- Manual drag-and-drop reordering. Favorites sort by recent activity client-side.
- A hard limit on the number of favorites per user.
- Mobile/terminal client support. The API is designed so those clients can adopt it later without server changes.
- Sharing favorites between users.
- Replacing or merging with the existing `Subscription.pin_to_top` feature. Favorites and pinning are independent: a channel can be either, both, or neither.

## 3. Data model

A new model in `zerver/models/user_favorites.py`:

```python
class UserFavorite(models.Model):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone_now)

    class Meta:
        unique_together = ("user_profile", "recipient")
        indexes = [models.Index(fields=["user_profile"])]
```

Rationale for one polymorphic table over `Subscription.is_favorite + UserFavoriteDM`:
- One code path for read, write, event, and audit, regardless of recipient type.
- Keeps `Subscription` row size unchanged. `Subscription` is one of the most-read tables in Zulip; adding a column would slightly hurt cache hit rate everywhere it is loaded.
- Easy to extend later (group DM support, custom labels, manual order) without touching `Subscription`.

Allowed `recipient.type` values, enforced at the view layer:
- `Recipient.STREAM` — only if the user has an active `Subscription` to that stream and the stream is not archived.
- `Recipient.PERSONAL` — only if the target user is active and not the requesting user themselves.
- `Recipient.DIRECT_MESSAGE_GROUP` — rejected with HTTP 400 for now.

## 4. API

### POST `/api/v1/users/me/favorites`

Add the given recipient to the user's favorites. Idempotent — adding an existing favorite returns 200 with no change.

Request body:
```json
{ "recipient_id": 12345 }
```

Response: `{"result": "success", "msg": ""}`.

Errors:
- 400 if `recipient_id` does not exist, is the user's own personal recipient, is a `DIRECT_MESSAGE_GROUP`, references a stream the user is not subscribed to, or references a deactivated user / archived stream.
- 401 if not authenticated.

### DELETE `/api/v1/users/me/favorites/<recipient_id>`

Remove the favorite. Idempotent — removing a non-existent favorite returns 200.

### Initial state via `/register`

`do_events_register` adds a new top-level field to the response:
```json
"favorites": [123, 456, 789]
```
A flat list of `recipient_id` values. The client looks each one up in its existing stream/user maps to render. One extra query per `/register`:
```sql
SELECT recipient_id FROM zerver_userfavorite WHERE user_profile_id = ?
```
Served by an index-only scan on the `(user_profile_id)` index from `unique_together`.

## 5. Event protocol

A new event type:
```json
{ "type": "user_favorite", "op": "add",    "recipient_id": 123 }
{ "type": "user_favorite", "op": "remove", "recipient_id": 123 }
```

Sent via `send_event_on_commit` to the affected user only (single recipient in the event-queue fanout). Mirrors the delivery cost of a `pin_to_top` change.

## 6. Backend implementation

### Action helpers

In `zerver/actions/user_favorites.py` (new file):

- `do_add_user_favorite(user_profile, recipient)` — INSERT (or no-op if exists), audit log, send event.
- `do_remove_user_favorite(user_profile, recipient)` — DELETE, audit log, send event.
- `do_remove_user_favorites_for_recipient(recipient)` — bulk DELETE across all users for one recipient (used by cleanup hooks); sends per-user events from the affected rows.
- `do_remove_all_user_favorites_for_user(user_profile)` — DELETE all of a user's favorites (used when the user is deactivated).

### View

`zerver/views/user_favorites.py` (new file) with two endpoints registered in `zproject/urls.py` under the `users/me/favorites` path. URL pattern follows the existing per-user settings convention.

### Auto-cleanup hooks

Inserted at the following call sites; each calls the matching helper above:

| Trigger | Existing function (file) | What to clean |
|---|---|---|
| User unsubscribes from stream | `bulk_remove_subscriptions` (`zerver/actions/streams.py`) | Favorite rows for that user × that stream's recipient |
| Stream archived | `do_deactivate_stream` (`zerver/actions/streams.py`) | All favorites with that stream's recipient |
| User deactivated | `do_deactivate_user` (`zerver/actions/users.py`) | (a) all favorites of that user; (b) all favorites pointing to that user's PERSONAL recipient |
| User reactivated | none | No action — favorites pointing to a deactivated personal recipient are already cleaned at deactivation time |

Each hook batches into a single DELETE query and emits one event per affected (user, recipient) pair.

### Audit log

Two new values in `RealmAuditLog.AuditLogEventType`:
- `USER_FAVORITE_ADDED = <next_free_id>`
- `USER_FAVORITE_REMOVED = <next_free_id>`

`extra_data` records `{"recipient_id": int, "recipient_type": int}`.

## 7. Frontend (web)

### State module

New `web/src/user_favorites.ts`:
- Holds `favorites: Set<number>` (recipient ids).
- `add(recipient_id)`, `remove(recipient_id)`, `is_favorite(recipient_id)`, `all_recipient_ids()`.
- Initialized from `page_params.favorites`.
- Subscribes to the `user_favorite` event and updates the set, then triggers sidebar re-render.

### Sidebar section

A new `#favorites` section above `#pinned-streams` in the left sidebar. Section render lives in a new `web/src/favorites_list.ts` that:
- Asks `user_favorites` for ids.
- For each id, resolves to either a stream (via `sub_store`) or a user (via `people`).
- Filters out anything no longer accessible (defensive — server cleanup should already have removed it).
- Sorts by recent activity: `max_message_id` from `message_store` for streams, and from `pm_conversations` for DMs. Higher first.
- Renders unread badges using `unread.num_unread_for_stream` / `unread.num_unread_for_user_ids_string`.
- Re-sorts on `message`, `unread`, and `user_favorite` events.

The section header shows total unread count for items inside it, matching the pattern in `stream_list.ts`.

### Entry points

1. **Sidebar context menu (right-click on a stream or DM row).** Add a "Add to favorites" / "Remove from favorites" item. Hook into the existing popover code in `web/src/popovers/` and `web/src/stream_popover.ts` / DM equivalent.
2. **Channel info / user info panel.** Add a toggle row in the existing settings/info modal for the channel and the user.

Keyboard shortcut and hover-star icon are deferred.

### Translation

All new user-visible strings ("Favorites", "Add to favorites", "Remove from favorites", aria-labels, tooltips) wrapped in `$t` / `_()` for i18n.

## 8. Database migration

One Django migration creating `zerver_userfavorite` with the table, indexes, and FKs. No data backfill.

## 9. Performance analysis

**Read path (`/register`):** one extra query, index-only scan on the `(user_profile_id)` index. With ~20 favorites/user expected, ~0.1–0.5 ms. Negligible against the dozens of queries already in `do_events_register`.

**Write path (toggle):** one INSERT or DELETE, one audit log INSERT, one event delivered to one user's queues. ~2–5 ms, equivalent to a `pin_to_top` toggle.

**Cleanup hooks:**
- Unsubscribe / archive stream: `DELETE WHERE recipient_id = ?` — single query using the FK index on `recipient_id`.
- Deactivate user: two `DELETE`s, each on an indexed column. Both run in the existing `do_deactivate_user` transaction.

**Storage:** ~30 bytes per row (incl. PK overhead). At 20 favorites/user × 10k DAU = ~6 MB. Indexes add roughly the same.

**Subscription table impact:** zero, by design. The polymorphic table avoids growing the `Subscription` row.

**Event traffic:** one event per toggle, delivered to one user. No fan-out cost.

## 10. Testing

### Backend (`zerver/tests/test_user_favorites.py`)

- Add/remove favorite — happy path for stream and personal recipient.
- Idempotency — add twice, remove twice.
- Validation: nonexistent recipient, group DM recipient, own personal recipient, unsubscribed stream, archived stream, deactivated target user.
- Auth: anonymous request rejected.
- Initial state: `/register` returns the favorites list.
- Cleanup:
  - Unsubscribe a favorited stream → favorite row gone, `user_favorite/remove` event delivered.
  - Archive a favorited stream → all subscribers' favorites gone, events delivered.
  - Deactivate a user → (a) their favorites gone; (b) favorites of others pointing at their personal recipient gone; events delivered.
- Audit log entries created with the expected `extra_data`.
- `test_events.py`: verify `user_favorite` event schema.
- Coverage: confirm new lines covered with `test-backend --coverage`.

### Frontend (`web/tests/`)

- `user_favorites.test.ts` — set add/remove, event handling.
- `favorites_list.test.ts` — sorting by activity, mixed channel + DM, filtering inaccessible items.
- `stream_list_sort.test.ts` — favorites section appears above pinned, both can coexist for the same channel.
- Update existing context-menu tests to assert the new menu item appears with the right label.

### Manual / visual

- Visual test (per CLAUDE.md): screenshot favorites section in light + dark theme; with 0, 1, and many favorites; mix of channel + DM; long names; narrow sidebar widths down to 480 px.
- Verify keyboard tab order through the new section.
- Verify aria-labels on the toggle controls.
- Verify behavior across two browser tabs (toggle in one → updates in the other via the event queue).

## 11. Documentation

- API: new entries in `zerver/openapi/zulip.yaml` for `POST /users/me/favorites` and `DELETE /users/me/favorites/{recipient_id}`, plus the new `user_favorite` event type. Reference the changelog file in `**Changes**` notes.
- API changelog: `tools/create-api-changelog` to generate `api_docs/unmerged.d/ZF-XXXXXX.md` describing the new endpoints, the new `favorites` field in `/register`, and the new event.
- Help center: a new MDX article at `starlight_help/src/content/docs/favorites.mdx` describing the feature, with a sidebar entry in `astro.config.mjs`.

## 12. Commit plan (preview)

Each commit self-contained, passing tests, no fixups:

1. `models: Add UserFavorite model and migration.`
2. `actions: Add user-favorites action helpers and audit-log events.`
3. `views: Add /users/me/favorites endpoints with validation.`
4. `events: Emit user_favorite events and include favorites in /register.`
5. `actions: Clean up favorites on unsubscribe, stream archive, and user deactivate.`
6. `web: Add user_favorites client state and event handler.`
7. `web: Render Favorites section in left sidebar above pinned streams.`
8. `web: Add favorite toggles to context menus and info panels.`
9. `api-docs: Document /users/me/favorites and user_favorite event.`
10. `help: Document the favorites feature.`

## 13. Open risks

- **Polling clients reading stale favorite state after a target becomes inaccessible.** Mitigated by server-side cleanup events; the client should also defensively filter at render time.
- **Private-channel access changes that don't go through `bulk_remove_subscriptions`.** Audit other code paths that revoke access (administrative removals, group changes); add cleanup there if any are missed.
- **Event-queue replay for offline clients.** A user offline during multiple toggles receives all events on reconnect, in order. Idempotent client handlers make this safe.
