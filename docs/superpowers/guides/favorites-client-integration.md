# Favorites — Client Integration Guide

**Audience:** Developers building or modifying a Zulip client (web app, mobile, desktop, terminal, third-party API consumer) to support the favorites feature.

**Prerequisites:** Familiarity with Zulip's [event-queue protocol](https://zulip.com/api/real-time-events) and the `/register` API.

**Related docs:**
- Spec: [`docs/superpowers/specs/2026-05-09-favorites-design.md`](../specs/2026-05-09-favorites-design.md)
- API reference: `zerver/openapi/zulip.yaml` (paths `/users/me/favorites`, the `user_favorite` event, and the `favorites` field of `/register`)
- API changelog: `api_docs/unmerged.d/ZF-b748fe.md`
- Server lifecycle notes: [`docs/subsystems/events-system.md`](../../subsystems/events-system.md) (section "`user_favorite` events")

---

## 1. What favorites are (and aren't)

A **favorite** is a per-user bookmark that pins a channel or 1-1 DM conversation to a dedicated section at the top of the conversation list. Favorites:

- Are **per user**. There is no realm-level or shared favorite list.
- Sync across the user's sessions through the event-queue.
- Persist across restarts (server-side storage).
- Are **independent of pinning** (`Subscription.pin_to_top`). A channel can be favorite, pinned, both, or neither.
- Are independent of muting, following, and stream colors.

Favorites are **not**:

- A way to subscribe to a channel. The user must already be subscribed; favoriting is purely UI surfacing.
- A way to start a DM. Favoriting a 1-1 DM with a user the requesting user has never DM'd before will create the underlying `DirectMessageGroup` row server-side, but the user still has to send a message themselves.
- Group DM support. Group DMs (3+ participants) are rejected for now. The wire format is forward-compatible — see [§9](#9-future-extensions).

---

## 2. The wire format

All API and event payloads use a `FavoriteTarget` object. Two shapes:

### 2.1 Channel

```json
{ "type": "channel", "id": 5 }
```

- `type` is the literal string `"channel"`.
- `id` is a `stream_id` (the same identifier used by the [narrow operator `channel`](https://zulip.com/api/construct-narrow), `Stream.stream_id` in `/register` subscription data, etc.).

### 2.2 1-1 DM

```json
{ "type": "dm", "user_ids": [12] }
```

- `type` is the literal string `"dm"`.
- `user_ids` is a list of **other** participants. For a 1-1 DM there is exactly one entry — the `user_id` of the other party. The requesting user is implicit and must **not** be included.

> The server resolves `user_ids` to a `DirectMessageGroup` recipient by combining the requesting user's id with `user_ids`, sorting, and looking up the group (creating it if absent). This matches the server's behavior for the [`POST /messages`](https://zulip.com/api/send-message) endpoint with `type=direct`.

### 2.3 Why two different shapes?

Channels are addressed by a stable numeric id. DMs are addressed by their participant set — that's the existing convention across narrow operators and the message-send endpoint, and it's what clients already track in their state (e.g., the web client's `pm_conversations` keys on a `user_ids_string`).

---

## 3. Reading initial state

The `/register` response includes a top-level `favorites` field when `user_favorite` is in `fetch_event_types`:

```jsonc
// Example slice of /register response
{
  "favorites": [
    { "type": "channel", "id": 5 },
    { "type": "channel", "id": 11 },
    { "type": "dm", "user_ids": [12] }
  ]
}
```

The list is **unordered**; the server makes no guarantees about ordering. Clients should sort it as they see fit. The reference web implementation sorts by recent activity (most recent message first), but ordering by display name, time-added, or any other criterion is fine.

If your client cannot adopt favorites in this release, simply ignore the field. It's additive and safe to skip.

### 3.1 Requesting the field

Add `user_favorite` to the `fetch_event_types` and `event_types` arrays in your `/register` request:

```http
POST /api/v1/register
Content-Type: application/x-www-form-urlencoded

fetch_event_types=["user_favorite", ...]
event_types=["user_favorite", ...]
```

If `user_favorite` is omitted from `fetch_event_types`, the `favorites` field is not present in the response.

---

## 4. Toggling a favorite

### 4.1 Add — `POST /api/v1/users/me/favorites`

Form-encoded body. For channels:

```http
POST /api/v1/users/me/favorites
Content-Type: application/x-www-form-urlencoded

type=channel&id=5
```

For 1-1 DMs (note `user_ids` is JSON-encoded since it's a list):

```http
POST /api/v1/users/me/favorites
Content-Type: application/x-www-form-urlencoded

type=dm&user_ids=%5B12%5D
```

(That URL-encoded body is `type=dm&user_ids=[12]`.)

Successful response: `{"result": "success", "msg": ""}`.

### 4.2 Remove — `DELETE /api/v1/users/me/favorites`

Same parameter shape, on the query string:

```
DELETE /api/v1/users/me/favorites?type=channel&id=5
DELETE /api/v1/users/me/favorites?type=dm&user_ids=%5B12%5D
```

### 4.3 Idempotency

Both endpoints are **idempotent**:

- `POST` with an already-favorited target → 200, no state change, **no event emitted**.
- `DELETE` with a target that isn't favorited → 200, no state change, **no event emitted**.

Clients **must not** depend on receiving an event for every API call. Use the API response (`200 success`) as confirmation; the event is only fired when state actually changed.

### 4.4 Validation errors

The server returns `400` with a `JsonError`-shaped response when:

- `type` is missing or not `"channel"`/`"dm"`.
- `type=channel` but `id` is missing, the channel doesn't exist or is archived, or the user is not subscribed.
- `type=dm` but `user_ids` is missing, empty, contains the requesting user's own id, or has more than one entry (group DMs rejected).
- The target user is deactivated.

Each error has a translated, human-readable `msg`. Surface it directly to the user when appropriate; do not parse the message text.

---

## 5. Receiving updates — the `user_favorite` event

```jsonc
{
  "id": 42,
  "type": "user_favorite",
  "op": "add",   // or "remove"
  "favorite": { "type": "channel", "id": 5 }
}
```

Apply to your local state:

```pseudocode
on_user_favorite_event(event):
    if event.op == "add":
        favorites.add(event.favorite)        // dedupe by deep-equality
    else:  # "remove"
        favorites.remove(event.favorite)     // no-op if absent
    rerender_sidebar()
```

### 5.1 Idempotent application

Replays must be safe. Treat duplicate `add`s and `remove`s of unknown targets as no-ops. This matters because:

- The event-queue may replay events on reconnect.
- Cleanup events (see §6) can race with explicit user actions.

### 5.2 Equality

Two `FavoriteTarget` objects are equal when their `type` matches and:

- For `channel`: same `id`.
- For `dm`: same `user_ids` list (same elements, same order — server always emits sorted).

A simple deep-equal check is sufficient. Don't compare on object identity.

### 5.3 Targeting

`user_favorite` events are **fan-out only to the affected user**. Clients only see events for their own favorites; you'll never receive a `user_favorite` event for another user.

---

## 6. Auto-cleanup semantics

The server proactively removes a favorite when it becomes meaningless. Clients receive a `user_favorite` event with `op="remove"` in three scenarios. The event arrives *after* the underlying state-change event (subscription remove, channel archive, etc.).

| Scenario | Server action | Event delivered |
|---|---|---|
| User unsubscribes from a favorited channel | `bulk_remove_subscriptions` deletes the favorite row | `user_favorite/remove` |
| A favorited channel is archived | `do_deactivate_stream` deletes favorites for all subscribers | `user_favorite/remove` per user |
| The user themselves is deactivated | `do_deactivate_user` deletes all of the user's favorites | (no event — queues are torn down) |

**One important non-cleanup:** if a 1-1 DM partner is deactivated, the favorite is **kept**. The underlying `DirectMessageGroup` row persists; only the partner's `Subscription.is_user_active` flips to `false`. The web client renders the partner with a deactivated badge but keeps the favorite row visible. If the user wants to drop the favorite, they remove it explicitly. This keeps deactivation cheap on the server.

Defensive client behavior: at render time, also filter out favorites whose target is no longer accessible (channel removed from local state, user not in `realm_users`). Server cleanup should make this redundant in normal operation, but a defensive filter prevents stale render in edge cases (e.g., a client that missed an event-queue catchup window).

---

## 7. Reference UI implementation (web)

The Zulip web app renders favorites in a dedicated **Favorites** section above the pinned-channels section in the left sidebar. Mixed channels + DMs in the same list, sorted by most recent activity. This is one valid choice — your client may render differently.

### 7.1 Recommended sources for sort keys

For each favorite row, you typically want:

- A **display name** — for channels: `Stream.name`. For DMs: the partner's `full_name`.
- A **last-activity timestamp / message id** — for channels: `max_message_id` from your message store. For DMs: `pm_conversations` (or your equivalent recent-conversations cache).
- An **unread count** — your existing unread-count infrastructure for streams and DMs works as-is.

### 7.2 Suggested entry points for toggling

- **Right-click / long-press menu** on a sidebar row: "Add to favorites" / "Remove from favorites".
- **Channel info / user info panel**: a checkbox or toggle.
- (Optional) **Keyboard shortcut** while viewing a narrow.

Show different labels based on `is_favorite` rather than greying out a single label. Keep the menu item visible regardless of state — discoverability matters.

### 7.3 Empty state

When the user has zero favorites, hide the section entirely (don't render an empty header). This avoids visual clutter for users who never adopt the feature.

---

## 8. Implementation checklist

A minimal end-to-end integration looks like:

- [ ] Add `user_favorite` to your `fetch_event_types` and `event_types` arrays.
- [ ] Read `register_response.favorites` into a client-side store (e.g., a `Set<FavoriteTarget>` or two `Set`s — one per type).
- [ ] Subscribe to `user_favorite` events; apply `add`/`remove` idempotently.
- [ ] Implement `POST /users/me/favorites` and `DELETE /users/me/favorites` with the wire format from §2.
- [ ] Wire up at least one entry point in your UI (context menu or info panel).
- [ ] Render a Favorites section in your sidebar (or wherever conversations are listed); hide when empty.
- [ ] Defensive render-time filter for inaccessible targets (channel not in subs, user not in realm_users).
- [ ] Display `is_favorite` state on toggle UI so users see what action is available.
- [ ] If your client supports translations: localize "Favorites", "Add to favorites", "Remove from favorites", aria-labels.

Not required (but nice to have):

- [ ] Section sort by recent activity.
- [ ] Keyboard shortcut.
- [ ] Section-header unread badge summing inner unreads.
- [ ] Optimistic UI: update the local set before the API request returns; revert on `4xx`.

---

## 9. Future extensions

The feature was scoped intentionally narrow. The wire format leaves room for:

- **Group DM favorites.** Lifting the validation requires accepting `user_ids` lists with length ≥ 2. The `FavoriteTarget` shape stays the same. Clients should already iterate `user_ids` rather than assume `user_ids[0]`.
- **Manual reorder.** Adding an `order` int (per-favorite, per-user) on the server side. Clients would gain a "drag to reorder" affordance.
- **Custom labels / groups.** Adding fields to `FavoriteTarget` is backwards-compatible if clients ignore unknown fields. (Per Zulip API convention — preserve unknown fields you don't recognize.)

If you build for the current spec, code defensively against length-1 `user_ids` instead of hardcoding "the other user is at index 0" and you'll have a smooth path to group-DM support later.

---

## 10. Testing your integration

Suggested manual test plan:

1. **Initial load.** Add a few favorites via API, then load `/register` — they appear in `favorites`.
2. **Add via API, observe in another tab.** Open two sessions; toggle in tab A; verify tab B updates from the event-queue without manual refresh.
3. **Idempotent toggle.** Click "Add to favorites" twice quickly; only one row appears.
4. **Cleanup — unsubscribe.** Favorite a channel, then unsubscribe; the favorite disappears.
5. **Cleanup — archive.** Have an admin archive a favorited channel; the favorite disappears.
6. **DM partner deactivated.** Favorite a DM partner, deactivate the partner; favorite **stays** but render reflects deactivated state.
7. **Group DM rejection.** Try to favorite a 3-person DM; expect 400.
8. **Self DM rejection.** Try to favorite a 1-1 DM with self; expect 400.
9. **Replay.** Disconnect the client for a while during which you toggle favorites in another session; reconnect and confirm state converges.

For automated tests, capture sample payloads with curl and replay them against the server in a test fixture; the wire format is small enough that schema-fuzzing is overkill.

---

## 11. FAQ

**Q: Why doesn't the server send `recipient_id` directly?**
A: `recipient_id` is server-internal. Clients work with `stream_id` and `user_id` everywhere else. Exposing the polymorphic `Recipient` would make clients maintain a `recipient_id → (type, id)` map for no benefit.

**Q: Why does favoriting a 1-1 DM auto-create the `DirectMessageGroup`?**
A: Same behavior as Zulip's send endpoint. The cost is one row in `zerver_huddle` plus two `Subscription` rows. The alternative (rejecting until both users have exchanged a message) was rejected as user-hostile.

**Q: What happens if I try to favorite the same channel from two devices simultaneously?**
A: One `INSERT` succeeds; the other becomes a no-op due to the unique constraint. Both devices receive a single `user_favorite/add` event. Idempotent semantics make races safe.

**Q: Why isn't there a `PATCH` to reorder?**
A: Reorder isn't in scope. Clients sort client-side. Adding an `order` column later is straightforward; until then, don't assume server-defined ordering.

**Q: Can I use `direct_message_group_id` as the wire id for DMs?**
A: No. The wire format is `user_ids` only. `DirectMessageGroup.id` is server-internal.

**Q: Is there a maximum number of favorites per user?**
A: No hard limit. The product team will impose one if it becomes a problem.

---

## 12. Versioning note

The feature is gated by API feature level **ZF-b748fe** (placeholder until the feature level is assigned at merge). Clients should check `zulip_feature_level` from `/server_settings` before assuming the endpoints exist; if absent, hide the favorites UI.
