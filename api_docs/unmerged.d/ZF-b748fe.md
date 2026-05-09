**Feature level ZF-b748fe**

* Added `POST /users/me/favorites` and `DELETE /users/me/favorites` endpoints
  for managing per-user favorited channels and 1-1 direct messages. Both
  endpoints accept a `{type, ...}` body where `type` is `"channel"` (with
  `id` set to a `stream_id`) or `"dm"` (with `user_ids` listing exactly
  one other user). Both are idempotent.
* Added a `favorites` field to the `/register` response, listing the user's
  favorited targets in the same wire shape used by the endpoints.
* Added a `user_favorite` event type. Sent on add/remove and on automatic
  cleanup when the user unsubscribes from a favorited channel, a favorited
  channel is archived, or the user themselves is deactivated. Cleanup
  events are fan-out only to the affected user. Group DMs are not yet
  supported.
