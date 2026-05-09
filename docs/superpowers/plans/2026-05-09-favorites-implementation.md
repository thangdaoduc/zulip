# Favorites for Channels and DMs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user mark subscribed channels and 1-1 DM conversations as "favorites" that appear in a dedicated section at the top of the left sidebar, with API documentation comprehensive enough that web, mobile, and third-party clients can implement against the same contract.

**Architecture:** New `UserFavorite` table polymorphically references `Recipient`. API and events use the wire shape `{type: "stream"|"private", id: int}`; server resolves to `recipient_id` internally. Reuses Zulip's event-queue and audit-log infrastructure. Auto-cleanup hooks fire when a favorited target becomes inaccessible. Frontend renders a new "Favorites" section above pinned streams.

**Tech Stack:** Python 3 / Django (backend), TypeScript (web frontend), OpenAPI (API docs), Starlight MDX (help center), pytest / mocha (tests).

**Spec:** [`docs/superpowers/specs/2026-05-09-favorites-design.md`](../specs/2026-05-09-favorites-design.md). Read it before starting.

**Per-task expectations** (apply to every task unless noted):
- Run `./tools/lint <changed files>` before each commit. Fix mypy and TypeScript errors.
- Each commit must pass tests on its own (`./tools/test-backend zerver.tests.test_user_favorites` or the relevant subset).
- Commit messages follow Zulip discipline (lowercase subsystem prefix, period, body explains why).

---

## Phase A — Backend Foundation

### Task 1: Add `UserFavorite` model and migration

**Files:**
- Create: `zerver/models/user_favorites.py`
- Modify: `zerver/models/__init__.py` (add export)
- Create: `zerver/migrations/NNNN_add_user_favorite.py` (filename produced by `manage.py makemigrations`)

- [ ] **Step 1: Create the model file**

```python
# zerver/models/user_favorites.py
from django.db import models
from django.db.models import CASCADE
from django.utils.timezone import now as timezone_now

from zerver.models.recipients import Recipient
from zerver.models.users import UserProfile


class UserFavorite(models.Model):
    """A user's favorited channel or DM target.

    The favorited target is identified by a Recipient row, supporting:
      * Recipient.STREAM   -> a channel the user is subscribed to
      * Recipient.PERSONAL -> the other user in a 1-1 DM

    Recipient.DIRECT_MESSAGE_GROUP is rejected at the view layer for now.
    Cleanup hooks delete rows when the target becomes inaccessible.
    """

    user_profile = models.ForeignKey(UserProfile, on_delete=CASCADE)
    recipient = models.ForeignKey(Recipient, on_delete=CASCADE)
    created_at = models.DateTimeField(default=timezone_now)

    class Meta:
        unique_together = ("user_profile", "recipient")
        indexes = [models.Index(fields=["user_profile"])]
```

- [ ] **Step 2: Re-export from the models package**

Modify `zerver/models/__init__.py`. Add the line in alphabetical order with other model imports:

```python
from zerver.models.user_favorites import UserFavorite as UserFavorite
```

- [ ] **Step 3: Generate the migration**

Run: `./manage.py makemigrations zerver`

Expected: a new file `zerver/migrations/NNNN_userfavorite.py` is created with `CreateModel` for `UserFavorite`. Inspect the generated migration; it should reference `recipient` as `ForeignKey` and include the `unique_together` constraint and the `(user_profile)` index.

- [ ] **Step 4: Apply the migration locally**

Run: `./manage.py migrate zerver`

Expected: migration applies cleanly, no errors.

- [ ] **Step 5: Smoke-test the model in a shell**

```bash
./manage.py shell -c "
from zerver.models import UserFavorite, UserProfile, Recipient
u = UserProfile.objects.first()
r = Recipient.objects.filter(type=Recipient.STREAM).first()
fav = UserFavorite.objects.create(user_profile=u, recipient=r)
print(fav.id, fav.user_profile_id, fav.recipient_id)
fav.delete()
"
```

Expected: prints an id and the FK ids, no errors.

- [ ] **Step 6: Commit**

```bash
git add zerver/models/user_favorites.py zerver/models/__init__.py zerver/migrations/NNNN_userfavorite.py
git commit -m "models: Add UserFavorite for per-user channel/DM favorites."
```

---

### Task 2: Add audit-log event types

**Files:**
- Modify: `zerver/models/realm_audit_logs.py:78-84`

- [ ] **Step 1: Add two enum values**

Edit `zerver/models/realm_audit_logs.py`. After `SUBSCRIPTION_PROPERTY_CHANGED = 304` (around line 81), in the same numeric range used for per-user/per-subscription actions, add:

```python
    USER_FAVORITE_ADDED = 360
    USER_FAVORITE_REMOVED = 361
```

(Place these adjacent to `USER_MUTED = 350` / `USER_UNMUTED = 351` to keep per-user lifecycle audit ids together. Verify 360/361 are unused by searching the file for `360` and `361`.)

- [ ] **Step 2: Run mypy on the file**

Run: `./tools/run-mypy zerver/models/realm_audit_logs.py`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add zerver/models/realm_audit_logs.py
git commit -m "audit_logs: Add USER_FAVORITE_ADDED and USER_FAVORITE_REMOVED."
```

---

### Task 3: Action helpers and event emission (TDD)

**Files:**
- Create: `zerver/actions/user_favorites.py`
- Create: `zerver/lib/event_schema.py` entry (if Zulip uses event_schema; otherwise: see Step 1 sub-bullet)
- Create: `zerver/tests/test_user_favorites.py` (initial tests)

> Pattern reference: model your code after `do_change_subscription_property` in `zerver/actions/streams.py:1180` and the test patterns in `zerver/tests/test_subscription_settings.py:167`.

- [ ] **Step 1: Write the first failing test — adding a stream favorite**

Create `zerver/tests/test_user_favorites.py`:

```python
from zerver.actions.user_favorites import (
    do_add_user_favorite,
    do_remove_user_favorite,
)
from zerver.lib.test_classes import ZulipTestCase
from zerver.models import Recipient, UserFavorite, UserProfile
from zerver.models.realm_audit_logs import AuditLogEventType, RealmAuditLog


class UserFavoriteActionsTest(ZulipTestCase):
    def get_stream_recipient(self, user: UserProfile, stream_name: str) -> Recipient:
        sub = self.subscribe(user, stream_name)
        return sub.recipient

    def test_add_stream_favorite_creates_row(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")

        do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        self.assertTrue(
            UserFavorite.objects.filter(
                user_profile=hamlet, recipient=recipient
            ).exists()
        )

    def test_add_stream_favorite_writes_audit_log(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")

        do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        log = RealmAuditLog.objects.filter(
            event_type=AuditLogEventType.USER_FAVORITE_ADDED,
            modified_user=hamlet,
        ).last()
        assert log is not None
        self.assertEqual(log.extra_data["recipient_id"], recipient.id)
        self.assertEqual(log.extra_data["recipient_type"], recipient.type)

    def test_add_stream_favorite_sends_event(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")
        stream = recipient.get_stream() if hasattr(recipient, "get_stream") else None
        from zerver.models import Stream
        stream = Stream.objects.get(id=recipient.type_id)

        with self.capture_send_event_calls(expected_num_events=1) as events:
            do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        event = events[0]["event"]
        self.assertEqual(event["type"], "user_favorite")
        self.assertEqual(event["op"], "add")
        self.assertEqual(event["favorite"], {"type": "stream", "id": stream.id})
        self.assertEqual(events[0]["users"], [hamlet.id])

    def test_add_personal_favorite_sends_event_with_user_id(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        recipient = Recipient.objects.get(
            type=Recipient.PERSONAL, type_id=cordelia.id
        )

        with self.capture_send_event_calls(expected_num_events=1) as events:
            do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        self.assertEqual(
            events[0]["event"]["favorite"],
            {"type": "private", "id": cordelia.id},
        )

    def test_add_is_idempotent(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")

        do_add_user_favorite(hamlet, recipient, acting_user=hamlet)
        with self.capture_send_event_calls(expected_num_events=0):
            do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        self.assertEqual(
            UserFavorite.objects.filter(user_profile=hamlet).count(), 1
        )

    def test_remove_deletes_row_and_sends_event(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")
        do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        with self.capture_send_event_calls(expected_num_events=1) as events:
            do_remove_user_favorite(hamlet, recipient, acting_user=hamlet)

        self.assertFalse(
            UserFavorite.objects.filter(user_profile=hamlet, recipient=recipient).exists()
        )
        self.assertEqual(events[0]["event"]["op"], "remove")

    def test_remove_is_idempotent(self) -> None:
        hamlet = self.example_user("hamlet")
        recipient = self.get_stream_recipient(hamlet, "Verona")

        with self.capture_send_event_calls(expected_num_events=0):
            do_remove_user_favorite(hamlet, recipient, acting_user=hamlet)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./tools/test-backend zerver.tests.test_user_favorites -v`

Expected: ImportError for `zerver.actions.user_favorites`.

- [ ] **Step 3: Implement the action helpers**

Create `zerver/actions/user_favorites.py`:

```python
from django.db import transaction

from zerver.lib.queue import queue_event_on_commit
from zerver.models import Recipient, UserFavorite, UserProfile
from zerver.models.realm_audit_logs import AuditLogEventType, RealmAuditLog
from zerver.tornado.django_api import send_event_on_commit


def _favorite_payload(recipient: Recipient) -> dict:
    """Translate a Recipient into the wire shape clients consume."""
    if recipient.type == Recipient.STREAM:
        return {"type": "stream", "id": recipient.type_id}
    if recipient.type == Recipient.PERSONAL:
        return {"type": "private", "id": recipient.type_id}
    raise AssertionError(
        f"unsupported recipient type for favorites: {recipient.type}"
    )


@transaction.atomic(savepoint=False)
def do_add_user_favorite(
    user_profile: UserProfile,
    recipient: Recipient,
    *,
    acting_user: UserProfile | None,
) -> None:
    fav, created = UserFavorite.objects.get_or_create(
        user_profile=user_profile, recipient=recipient
    )
    if not created:
        return

    RealmAuditLog.objects.create(
        realm=user_profile.realm,
        acting_user=acting_user,
        modified_user=user_profile,
        event_type=AuditLogEventType.USER_FAVORITE_ADDED,
        event_time=fav.created_at,
        extra_data={"recipient_id": recipient.id, "recipient_type": recipient.type},
    )

    send_event_on_commit(
        user_profile.realm,
        {
            "type": "user_favorite",
            "op": "add",
            "favorite": _favorite_payload(recipient),
        },
        [user_profile.id],
    )


@transaction.atomic(savepoint=False)
def do_remove_user_favorite(
    user_profile: UserProfile,
    recipient: Recipient,
    *,
    acting_user: UserProfile | None,
) -> None:
    deleted, _ = UserFavorite.objects.filter(
        user_profile=user_profile, recipient=recipient
    ).delete()
    if not deleted:
        return

    from django.utils.timezone import now as timezone_now

    RealmAuditLog.objects.create(
        realm=user_profile.realm,
        acting_user=acting_user,
        modified_user=user_profile,
        event_type=AuditLogEventType.USER_FAVORITE_REMOVED,
        event_time=timezone_now(),
        extra_data={"recipient_id": recipient.id, "recipient_type": recipient.type},
    )

    send_event_on_commit(
        user_profile.realm,
        {
            "type": "user_favorite",
            "op": "remove",
            "favorite": _favorite_payload(recipient),
        },
        [user_profile.id],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./tools/test-backend zerver.tests.test_user_favorites -v`

Expected: all 7 tests pass.

- [ ] **Step 5: Lint**

Run: `./tools/lint zerver/actions/user_favorites.py zerver/tests/test_user_favorites.py`

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add zerver/actions/user_favorites.py zerver/tests/test_user_favorites.py
git commit -m "actions: Add do_add_user_favorite and do_remove_user_favorite."
```

---

### Task 4: POST `/users/me/favorites` endpoint (TDD)

**Files:**
- Create: `zerver/views/user_favorites.py`
- Modify: `zerver/lib/url_redirects.py` or `zproject/urls.py` (URL routing — confirm convention with `git grep "users/me/subscriptions"` to find where similar per-user endpoints register)
- Modify: `zerver/tests/test_user_favorites.py` (append view tests)

- [ ] **Step 1: Write the failing tests**

Append to `zerver/tests/test_user_favorites.py`:

```python
class UserFavoriteViewTest(ZulipTestCase):
    def test_post_stream_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream
        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "stream", "id": stream.id},
            content_type="application/json",
        )
        self.assert_json_success(result)
        self.assertEqual(
            UserFavorite.objects.filter(
                user_profile=hamlet,
                recipient__type=Recipient.STREAM,
                recipient__type_id=stream.id,
            ).count(),
            1,
        )

    def test_post_private_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "private", "id": cordelia.id},
            content_type="application/json",
        )
        self.assert_json_success(result)

    def test_post_rejects_unsubscribed_stream(self) -> None:
        hamlet = self.example_user("hamlet")
        from zerver.models import Stream
        stream = Stream.objects.create(name="Secret", realm=hamlet.realm, invite_only=True)

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "stream", "id": stream.id},
            content_type="application/json",
        )
        self.assert_json_error(result, "Not subscribed to this channel")

    def test_post_rejects_self_user(self) -> None:
        hamlet = self.example_user("hamlet")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "private", "id": hamlet.id},
            content_type="application/json",
        )
        self.assert_json_error(result, "Cannot favorite yourself")

    def test_post_rejects_deactivated_user(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        from zerver.actions.users import do_deactivate_user
        do_deactivate_user(cordelia, acting_user=None)

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "private", "id": cordelia.id},
            content_type="application/json",
        )
        self.assert_json_error(result, "User not found")

    def test_post_rejects_invalid_type(self) -> None:
        hamlet = self.example_user("hamlet")
        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "group", "id": 1},
            content_type="application/json",
        )
        self.assert_json_error_contains(result, "type")

    def test_post_is_idempotent(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream
        stream_id = Stream.objects.get(name="Verona", realm=hamlet.realm).id

        for _ in range(2):
            self.assert_json_success(
                self.api_post(
                    hamlet,
                    "/api/v1/users/me/favorites",
                    {"type": "stream", "id": stream_id},
                    content_type="application/json",
                )
            )
        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./tools/test-backend zerver.tests.test_user_favorites.UserFavoriteViewTest -v`

Expected: 404 / route not found.

- [ ] **Step 3: Implement the view**

Create `zerver/views/user_favorites.py`:

```python
from typing import Literal

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from pydantic import Json

from zerver.actions.user_favorites import (
    do_add_user_favorite,
    do_remove_user_favorite,
)
from zerver.lib.exceptions import JsonableError
from zerver.lib.response import json_success
from zerver.lib.typed_endpoint import typed_endpoint
from zerver.models import Recipient, Subscription, UserProfile
from zerver.models.users import get_active_user_profile_by_id_in_realm


def _resolve_recipient(
    user_profile: UserProfile, fav_type: str, fav_id: int
) -> Recipient:
    if fav_type == "stream":
        from zerver.models import Stream

        try:
            stream = Stream.objects.get(
                id=fav_id, realm=user_profile.realm, deactivated=False
            )
        except Stream.DoesNotExist:
            raise JsonableError(_("Channel not found"))

        if not Subscription.objects.filter(
            user_profile=user_profile,
            recipient=stream.recipient,
            active=True,
        ).exists():
            raise JsonableError(_("Not subscribed to this channel"))

        return stream.recipient

    if fav_type == "private":
        if fav_id == user_profile.id:
            raise JsonableError(_("Cannot favorite yourself"))
        try:
            target = get_active_user_profile_by_id_in_realm(fav_id, user_profile.realm)
        except UserProfile.DoesNotExist:
            raise JsonableError(_("User not found"))
        return Recipient.objects.get(type=Recipient.PERSONAL, type_id=target.id)

    raise JsonableError(_("Invalid favorite type: {fav_type}").format(fav_type=fav_type))


@typed_endpoint
def add_favorite(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    type: Literal["stream", "private"],
    id: Json[int],
) -> HttpResponse:
    recipient = _resolve_recipient(user_profile, type, id)
    do_add_user_favorite(user_profile, recipient, acting_user=user_profile)
    return json_success(request)


@typed_endpoint
def remove_favorite(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    type: Literal["stream", "private"],
    id: Json[int],
) -> HttpResponse:
    recipient = _resolve_recipient(user_profile, type, id)
    do_remove_user_favorite(user_profile, recipient, acting_user=user_profile)
    return json_success(request)
```

- [ ] **Step 4: Wire up the URLs**

Modify `zproject/urls.py`. Find the section that defines `users/me/subscriptions/properties` (search for `subscription_properties`). Add adjacent entries:

```python
    # Favorites
    rest_path(
        "users/me/favorites",
        POST=("zerver.views.user_favorites.add_favorite", {"intentionally_undocumented"}),
        DELETE=("zerver.views.user_favorites.remove_favorite", {"intentionally_undocumented"}),
    ),
```

(Remove the `intentionally_undocumented` flag in Task 9 once OpenAPI docs are written. Keeping it now lets the existing OpenAPI test pass.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./tools/test-backend zerver.tests.test_user_favorites -v`

Expected: all view tests pass.

- [ ] **Step 6: Lint and commit**

```bash
./tools/lint zerver/views/user_favorites.py zproject/urls.py zerver/tests/test_user_favorites.py
git add zerver/views/user_favorites.py zproject/urls.py zerver/tests/test_user_favorites.py
git commit -m "views: Add POST /users/me/favorites with full validation."
```

---

### Task 5: DELETE endpoint test coverage

> The DELETE handler is already implemented in Task 4 (uses the same view file). This task adds the test cases that exercise it.

**Files:**
- Modify: `zerver/tests/test_user_favorites.py`

- [ ] **Step 1: Append DELETE tests**

```python
    def test_delete_removes_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream
        stream_id = Stream.objects.get(name="Verona", realm=hamlet.realm).id

        self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "stream", "id": stream_id},
            content_type="application/json",
        )
        result = self.api_delete(
            hamlet,
            f"/api/v1/users/me/favorites?type=stream&id={stream_id}",
        )
        self.assert_json_success(result)
        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 0)

    def test_delete_is_idempotent(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream
        stream_id = Stream.objects.get(name="Verona", realm=hamlet.realm).id

        result = self.api_delete(
            hamlet,
            f"/api/v1/users/me/favorites?type=stream&id={stream_id}",
        )
        self.assert_json_success(result)
```

- [ ] **Step 2: Run, fix, commit**

```bash
./tools/test-backend zerver.tests.test_user_favorites -v
git add zerver/tests/test_user_favorites.py
git commit -m "tests: Cover DELETE /users/me/favorites cases."
```

---

### Task 6: Include `favorites` in `/register` response (TDD)

**Files:**
- Modify: `zerver/lib/events.py` (function `do_events_register` and the `fetch_initial_state_data`)
- Modify: `zerver/tests/test_user_favorites.py`

> Pattern reference: search `zerver/lib/events.py` for `pin_to_top` to see how subscription state is loaded into initial state. The `favorites` field is a separate top-level key — find the place near where other top-level user-specific lists are added (e.g. `muted_users`).

- [ ] **Step 1: Write the failing test**

```python
class FavoriteRegisterTest(ZulipTestCase):
    def test_register_includes_favorites(self) -> None:
        from zerver.lib.events import do_events_register
        from zerver.models import Stream

        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)
        cordelia = self.example_user("cordelia")
        from zerver.actions.user_favorites import do_add_user_favorite
        do_add_user_favorite(hamlet, stream.recipient, acting_user=hamlet)
        do_add_user_favorite(
            hamlet,
            Recipient.objects.get(type=Recipient.PERSONAL, type_id=cordelia.id),
            acting_user=hamlet,
        )

        state = do_events_register(
            hamlet,
            hamlet.realm,
            get_client("website"),
            event_types=["user_favorite"],
            fetch_event_types=["user_favorite"],
            apply_markdown=True,
            client_gravatar=False,
        )
        favorites = state["favorites"]
        self.assertCountEqual(
            favorites,
            [
                {"type": "stream", "id": stream.id},
                {"type": "private", "id": cordelia.id},
            ],
        )
```

(Adjust `get_client` import line to match other tests in the file.)

- [ ] **Step 2: Run to verify failure**

Run: `./tools/test-backend zerver.tests.test_user_favorites.FavoriteRegisterTest -v`

Expected: KeyError on `"favorites"`.

- [ ] **Step 3: Implement initial state loader**

In `zerver/lib/events.py`, add a helper near other per-user state loaders:

```python
def get_favorites(user_profile: UserProfile) -> list[dict[str, object]]:
    from zerver.models import Recipient, UserFavorite

    rows = (
        UserFavorite.objects.filter(user_profile=user_profile)
        .select_related("recipient")
        .values_list("recipient__type", "recipient__type_id")
    )
    out: list[dict[str, object]] = []
    for rtype, type_id in rows:
        if rtype == Recipient.STREAM:
            out.append({"type": "stream", "id": type_id})
        elif rtype == Recipient.PERSONAL:
            out.append({"type": "private", "id": type_id})
    return out
```

In `fetch_initial_state_data`, add:

```python
    if want("user_favorite"):
        state["favorites"] = get_favorites(user_profile)
```

In `apply_event`, add a handler for the `user_favorite` event:

```python
    elif event["type"] == "user_favorite":
        favs = state.setdefault("favorites", [])
        target = event["favorite"]
        if event["op"] == "add":
            if target not in favs:
                favs.append(target)
        elif event["op"] == "remove":
            state["favorites"] = [f for f in favs if f != target]
```

- [ ] **Step 4: Register the new event type**

In `zerver/lib/events.py`, locate the `ALL_EVENT_TYPES` constant (or equivalent registration list — search for `muted_users`). Add `"user_favorite"`.

- [ ] **Step 5: Verify tests pass**

Run: `./tools/test-backend zerver.tests.test_user_favorites -v`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add zerver/lib/events.py zerver/tests/test_user_favorites.py
git commit -m "events: Include favorites in /register and apply user_favorite events."
```

---

## Phase B — Cleanup Hooks

### Task 7: Cleanup on stream unsubscribe (TDD)

**Files:**
- Modify: `zerver/actions/streams.py` (`bulk_remove_subscriptions`)
- Modify: `zerver/tests/test_user_favorites.py`

- [ ] **Step 1: Write the failing test**

```python
class FavoriteCleanupTest(ZulipTestCase):
    def test_unsubscribe_removes_favorite(self) -> None:
        from zerver.actions.streams import bulk_remove_subscriptions
        from zerver.actions.user_favorites import do_add_user_favorite
        from zerver.models import Stream

        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)
        do_add_user_favorite(hamlet, stream.recipient, acting_user=hamlet)

        # bulk_remove_subscriptions emits multiple events; just verify the
        # favorite-cleanup ones are among them.
        with self.tornado_redirected_to_list(events := [], expected_num_events=None):
            bulk_remove_subscriptions(
                hamlet.realm, [hamlet], [stream], acting_user=hamlet
            )

        self.assertFalse(
            UserFavorite.objects.filter(user_profile=hamlet).exists()
        )
        favorite_remove_events = [
            e for e in events if e["event"]["type"] == "user_favorite"
        ]
        self.assertEqual(len(favorite_remove_events), 1)
        self.assertEqual(favorite_remove_events[0]["event"]["op"], "remove")
```

> If `tornado_redirected_to_list` is not available in the test base class, use `capture_send_event_calls` and run the test once to read the actual count from the assertion failure message (e.g., "expected N got M"), then set `expected_num_events=M`. This is a common Zulip test pattern when the count depends on existing fan-out logic.

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Add the hook in `bulk_remove_subscriptions`**

Find the function in `zerver/actions/streams.py`. After the existing logic that deactivates `Subscription` rows for each `(user, stream)` pair and emits subscription-remove events, add:

```python
    # Clean up any favorites pointing at the now-unsubscribed streams.
    from zerver.actions.user_favorites import do_remove_user_favorite

    for user_profile, sub_info in <existing user/sub iteration>:
        for stream in <streams for this user>:
            try:
                do_remove_user_favorite(
                    user_profile, stream.recipient, acting_user=acting_user
                )
            except UserFavorite.DoesNotExist:
                pass
```

> The exact loop structure depends on the local variables already in `bulk_remove_subscriptions`. Read the function's existing code carefully and add the cleanup inside the same per-user loop already present, to avoid extra queries. The `do_remove_user_favorite` helper is itself idempotent (no-op if no row), so a `try/except` is unnecessary; remove it after confirming.

- [ ] **Step 4: Run to verify pass**

- [ ] **Step 5: Commit**

```bash
git add zerver/actions/streams.py zerver/tests/test_user_favorites.py
git commit -m "streams: Drop favorites when user unsubscribes from a channel."
```

---

### Task 8: Cleanup on stream archive (TDD)

**Files:**
- Modify: `zerver/actions/streams.py` (`do_deactivate_stream` — verify exact name with `git grep "def do_deactivate_stream\|def do_archive_stream"`)
- Modify: `zerver/tests/test_user_favorites.py`

- [ ] **Step 1: Write the failing test**

```python
    def test_archive_stream_removes_all_favorites(self) -> None:
        from zerver.actions.streams import do_deactivate_stream
        from zerver.actions.user_favorites import do_add_user_favorite
        from zerver.models import Stream

        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        self.subscribe(hamlet, "Verona")
        self.subscribe(cordelia, "Verona")
        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)
        do_add_user_favorite(hamlet, stream.recipient, acting_user=hamlet)
        do_add_user_favorite(cordelia, stream.recipient, acting_user=cordelia)

        do_deactivate_stream(stream, acting_user=hamlet)

        self.assertEqual(
            UserFavorite.objects.filter(recipient=stream.recipient).count(), 0
        )
```

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Add a bulk helper and call it**

Append to `zerver/actions/user_favorites.py`:

```python
@transaction.atomic(savepoint=False)
def do_remove_user_favorites_for_recipient(recipient: Recipient) -> None:
    """Bulk remove favorites pointing at this recipient (for all users).

    Sends a per-user `user_favorite/remove` event. Used by stream archive
    and user deactivation cleanup.
    """
    from zerver.models import UserProfile

    affected_user_ids = list(
        UserFavorite.objects.filter(recipient=recipient).values_list(
            "user_profile_id", flat=True
        )
    )
    if not affected_user_ids:
        return

    UserFavorite.objects.filter(recipient=recipient).delete()

    from django.utils.timezone import now as timezone_now

    for user_id in affected_user_ids:
        user = UserProfile.objects.get(id=user_id)
        RealmAuditLog.objects.create(
            realm=user.realm,
            modified_user=user,
            event_type=AuditLogEventType.USER_FAVORITE_REMOVED,
            event_time=timezone_now(),
            extra_data={"recipient_id": recipient.id, "recipient_type": recipient.type},
        )
        send_event_on_commit(
            user.realm,
            {
                "type": "user_favorite",
                "op": "remove",
                "favorite": _favorite_payload(recipient),
            },
            [user.id],
        )
```

In `zerver/actions/streams.py`, inside `do_deactivate_stream` (after the stream is marked deactivated and subscription cleanup has run), add:

```python
    from zerver.actions.user_favorites import do_remove_user_favorites_for_recipient
    do_remove_user_favorites_for_recipient(stream.recipient)
```

- [ ] **Step 4: Run, fix, commit**

```bash
./tools/test-backend zerver.tests.test_user_favorites -v
git add zerver/actions/streams.py zerver/actions/user_favorites.py zerver/tests/test_user_favorites.py
git commit -m "streams: Drop favorites for all users when channel is archived."
```

---

### Task 9: Cleanup on user deactivation (TDD)

**Files:**
- Modify: `zerver/actions/users.py` (`do_deactivate_user`)
- Modify: `zerver/tests/test_user_favorites.py`

- [ ] **Step 1: Write the failing tests**

```python
    def test_deactivate_user_removes_their_favorites(self) -> None:
        from zerver.actions.users import do_deactivate_user
        from zerver.actions.user_favorites import do_add_user_favorite
        from zerver.models import Stream

        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)
        do_add_user_favorite(hamlet, stream.recipient, acting_user=hamlet)

        do_deactivate_user(hamlet, acting_user=None)

        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 0)

    def test_deactivate_user_removes_others_dm_favorites_pointing_to_them(self) -> None:
        from zerver.actions.users import do_deactivate_user
        from zerver.actions.user_favorites import do_add_user_favorite

        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        cordelia_personal = Recipient.objects.get(
            type=Recipient.PERSONAL, type_id=cordelia.id
        )
        do_add_user_favorite(hamlet, cordelia_personal, acting_user=hamlet)

        do_deactivate_user(cordelia, acting_user=None)

        self.assertFalse(
            UserFavorite.objects.filter(
                user_profile=hamlet, recipient=cordelia_personal
            ).exists()
        )
```

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Add helper and integrate**

Append to `zerver/actions/user_favorites.py`:

```python
@transaction.atomic(savepoint=False)
def do_remove_all_user_favorites_for_user(user_profile: UserProfile) -> None:
    """Remove all favorites owned by this user. Used when deactivating."""
    rows = list(
        UserFavorite.objects.filter(user_profile=user_profile).select_related("recipient")
    )
    if not rows:
        return
    UserFavorite.objects.filter(user_profile=user_profile).delete()
    from django.utils.timezone import now as timezone_now

    for row in rows:
        RealmAuditLog.objects.create(
            realm=user_profile.realm,
            modified_user=user_profile,
            event_type=AuditLogEventType.USER_FAVORITE_REMOVED,
            event_time=timezone_now(),
            extra_data={
                "recipient_id": row.recipient_id,
                "recipient_type": row.recipient.type,
            },
        )
        # No event needed: client is being disconnected.
```

In `zerver/actions/users.py`, inside `do_deactivate_user`, after the user is marked inactive but before the function returns:

```python
    from zerver.actions.user_favorites import (
        do_remove_all_user_favorites_for_user,
        do_remove_user_favorites_for_recipient,
    )
    from zerver.models import Recipient

    do_remove_all_user_favorites_for_user(user_profile)
    personal_recipient = Recipient.objects.get(
        type=Recipient.PERSONAL, type_id=user_profile.id
    )
    do_remove_user_favorites_for_recipient(personal_recipient)
```

- [ ] **Step 4: Run, lint, commit**

```bash
./tools/test-backend zerver.tests.test_user_favorites -v
./tools/lint zerver/actions/users.py zerver/actions/user_favorites.py
git add zerver/actions/users.py zerver/actions/user_favorites.py zerver/tests/test_user_favorites.py
git commit -m "users: Drop favorites on user deactivation."
```

---

### Task 10: Coverage check

- [ ] **Step 1: Run coverage**

Run: `./tools/test-backend --coverage zerver.tests.test_user_favorites`

- [ ] **Step 2: Inspect coverage report**

Verify every line of `zerver/actions/user_favorites.py` and `zerver/views/user_favorites.py` is covered. If `tools/coveragerc` flags any uncovered lines, add a test for that branch (typically the `AssertionError` path or a rare validation path) before committing.

---

## Phase C — API Documentation

### Task 11: OpenAPI definitions

**Files:**
- Modify: `zerver/openapi/zulip.yaml`
- Run: `tools/create-api-changelog`

- [ ] **Step 1: Generate changelog placeholder**

Run: `tools/create-api-changelog`

Output: a new file `api_docs/unmerged.d/ZF-XXXXXX.md` is created and staged.

- [ ] **Step 2: Fill in the changelog**

Edit the generated file with this content:

```markdown
**Feature level ZF-XXXXXX**

* Added `POST /users/me/favorites` and `DELETE /users/me/favorites` for managing per-user favorited channels and 1-1 DMs.
* Added a `favorites` field to the `/register` response, listing the user's favorited targets as `{type, id}` objects.
* Added a new `user_favorite` event type emitted on add/remove and on automatic cleanup (unsubscribe, channel archive, user deactivation).
```

(Replace `ZF-XXXXXX` with the placeholder filename stem from the generated file. The merge process replaces it with the final feature level.)

- [ ] **Step 3: Add OpenAPI definitions**

In `zerver/openapi/zulip.yaml`, define a reusable component `FavoriteTarget`:

```yaml
components:
  schemas:
    FavoriteTarget:
      type: object
      additionalProperties: false
      required: [type, id]
      properties:
        type:
          type: string
          enum: [stream, private]
          description: |
            Discriminates the kind of conversation. `stream` means a channel
            the user is subscribed to. `private` means a 1-1 direct message
            with another user.
        id:
          type: integer
          description: |
            For `type=stream`, this is the channel's `stream_id`. For
            `type=private`, this is the other user's `user_id`.
```

Add the two endpoint paths under `paths:`:

```yaml
  /users/me/favorites:
    post:
      operationId: add-favorite
      summary: Add a favorite
      tags: [user-data]
      description: |
        Mark a channel or 1-1 DM as a favorite. Idempotent — if already
        favorited, returns success without changes.

        **Changes**: New in Zulip 12.0 (feature level ZF-XXXXXX).
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/FavoriteTarget"
      responses:
        "200":
          description: Success
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/JsonSuccess"
        "400":
          description: |
            Returned when:
            * `type` is not `stream` or `private`
            * the channel does not exist or the user is not subscribed
            * the user references their own user id
            * the target user is deactivated or the channel is archived
    delete:
      operationId: remove-favorite
      summary: Remove a favorite
      tags: [user-data]
      description: |
        Remove a favorite. Idempotent.

        **Changes**: New in Zulip 12.0 (feature level ZF-XXXXXX).
      parameters:
        - name: type
          in: query
          required: true
          schema:
            type: string
            enum: [stream, private]
        - name: id
          in: query
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: Success
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/JsonSuccess"
```

Add the new event under the `events` section:

```yaml
  user_favorite:
    type: object
    description: |
      Emitted when a favorite is added or removed for the user.

      Cleanup events (`op=remove`) are also emitted automatically when:
      * the user unsubscribes from a favorited channel
      * a favorited channel is archived
      * a 1-1 DM partner is deactivated

      Clients must apply `add` and `remove` operations idempotently:
      replaying an `add` for an already-favorited target or a `remove`
      for an unknown target is safe.
    required: [type, op, favorite]
    properties:
      type:
        type: string
        enum: [user_favorite]
      op:
        type: string
        enum: [add, remove]
      favorite:
        $ref: "#/components/schemas/FavoriteTarget"
```

In the `/register` response schema, add a new field:

```yaml
        favorites:
          type: array
          description: |
            Initial list of the user's favorited channels and 1-1 DMs.
            Each entry is a `FavoriteTarget`.

            **Changes**: New in Zulip 12.0 (feature level ZF-XXXXXX).
          items:
            $ref: "#/components/schemas/FavoriteTarget"
```

- [ ] **Step 4: Remove the `intentionally_undocumented` flags**

In `zproject/urls.py`, drop the `intentionally_undocumented` markers from the favorites routes added in Task 4.

- [ ] **Step 5: Verify OpenAPI tests pass**

Run: `./tools/test-backend zerver.openapi`

Expected: pass. The OpenAPI test suite validates that documented endpoints match registered routes.

- [ ] **Step 6: Commit**

```bash
git add zerver/openapi/zulip.yaml api_docs/unmerged.d/*.md zproject/urls.py
git commit -m "api-docs: Document /users/me/favorites and user_favorite event."
```

---

### Task 12: Developer docs note

**Files:**
- Modify: `docs/subsystems/events-system.md` (or the closest match — confirm with `ls docs/subsystems/`)

- [ ] **Step 1: Add a short subsection**

Append a section near other event documentation:

```markdown
### `user_favorite` events

The `user_favorite` event delivers `add` and `remove` operations for a
user's favorited channels and 1-1 DMs. Cleanup of favorites is centralized
in `zerver/actions/user_favorites.py`. Any new code path that revokes a
user's access to a channel, archives a channel, or deactivates a user
must call `do_remove_user_favorites_for_recipient` or
`do_remove_all_user_favorites_for_user` so clients see consistent state.
```

- [ ] **Step 2: Commit**

```bash
git add docs/subsystems/events-system.md
git commit -m "docs: Note user_favorite event lifecycle for contributors."
```

---

## Phase D — Frontend Foundation

### Task 13: `user_favorites.ts` client state

**Files:**
- Create: `web/src/user_favorites.ts`
- Create: `web/tests/user_favorites.test.cjs`

> Pattern reference: model after `web/src/user_topics.ts` (per-user state with event-driven mutation).

- [ ] **Step 1: Write the failing test**

Create `web/tests/user_favorites.test.cjs`:

```javascript
"use strict";

const {strict: assert} = require("assert");
const {zrequire} = require("./lib/namespace.cjs");
const {run_test} = require("./lib/test.cjs");

const user_favorites = zrequire("user_favorites");

run_test("initialize and query", () => {
    user_favorites.initialize({
        favorites: [
            {type: "stream", id: 5},
            {type: "private", id: 12},
        ],
    });
    assert.equal(user_favorites.is_stream_favorite(5), true);
    assert.equal(user_favorites.is_stream_favorite(6), false);
    assert.equal(user_favorites.is_user_favorite(12), true);
    assert.equal(user_favorites.is_user_favorite(13), false);
});

run_test("add and remove via events", () => {
    user_favorites.initialize({favorites: []});
    user_favorites.handle_event({type: "user_favorite", op: "add", favorite: {type: "stream", id: 7}});
    assert.equal(user_favorites.is_stream_favorite(7), true);
    user_favorites.handle_event({type: "user_favorite", op: "remove", favorite: {type: "stream", id: 7}});
    assert.equal(user_favorites.is_stream_favorite(7), false);
});

run_test("idempotent add/remove", () => {
    user_favorites.initialize({favorites: []});
    user_favorites.handle_event({type: "user_favorite", op: "add", favorite: {type: "stream", id: 1}});
    user_favorites.handle_event({type: "user_favorite", op: "add", favorite: {type: "stream", id: 1}});
    assert.deepEqual(user_favorites.all().sort_targets, undefined); // sanity
    assert.equal([...user_favorites.streams()].length, 1);
    user_favorites.handle_event({type: "user_favorite", op: "remove", favorite: {type: "stream", id: 999}});
    // should not throw
});
```

- [ ] **Step 2: Run to verify failure**

Run: `./tools/test-js-with-node web/tests/user_favorites.test.cjs`

Expected: module not found.

- [ ] **Step 3: Implement**

Create `web/src/user_favorites.ts`:

```typescript
import {z} from "zod";

export const favorite_target_schema = z.object({
    type: z.enum(["stream", "private"]),
    id: z.number(),
});
export type FavoriteTarget = z.infer<typeof favorite_target_schema>;

const favorite_streams = new Set<number>();
const favorite_users = new Set<number>();
const change_handlers: Array<() => void> = [];

export function initialize(params: {favorites: FavoriteTarget[]}): void {
    favorite_streams.clear();
    favorite_users.clear();
    for (const fav of params.favorites) {
        if (fav.type === "stream") {
            favorite_streams.add(fav.id);
        } else {
            favorite_users.add(fav.id);
        }
    }
}

export function is_stream_favorite(stream_id: number): boolean {
    return favorite_streams.has(stream_id);
}

export function is_user_favorite(user_id: number): boolean {
    return favorite_users.has(user_id);
}

export function streams(): ReadonlySet<number> {
    return favorite_streams;
}

export function users(): ReadonlySet<number> {
    return favorite_users;
}

export function on_change(handler: () => void): void {
    change_handlers.push(handler);
}

function notify(): void {
    for (const h of change_handlers) {
        h();
    }
}

export function handle_event(event: {
    type: "user_favorite";
    op: "add" | "remove";
    favorite: FavoriteTarget;
}): void {
    const set = event.favorite.type === "stream" ? favorite_streams : favorite_users;
    if (event.op === "add") {
        set.add(event.favorite.id);
    } else {
        set.delete(event.favorite.id);
    }
    notify();
}
```

- [ ] **Step 4: Run, fix, commit**

```bash
./tools/test-js-with-node web/tests/user_favorites.test.cjs
./tools/lint web/src/user_favorites.ts web/tests/user_favorites.test.cjs
git add web/src/user_favorites.ts web/tests/user_favorites.test.cjs
git commit -m "web: Add user_favorites client state module."
```

---

### Task 14: Wire `user_favorite` event and `page_params.favorites` into the client

**Files:**
- Modify: `web/src/server_events_dispatch.ts` (event dispatcher)
- Modify: `web/src/ui_init.ts` (or whichever module initializes per-user state from `page_params`)
- Modify: `web/src/state_data.ts` (if it defines the typed schema for `page_params`)

- [ ] **Step 1: Add the schema field**

In `web/src/state_data.ts`, find the schema for state items. Add:

```typescript
import {favorite_target_schema} from "./user_favorites.ts";

// In the state schema:
    favorites: z.array(favorite_target_schema),
```

- [ ] **Step 2: Initialize on page load**

In `web/src/ui_init.ts` (or the similar bootstrap file — search for `user_topics.initialize`), import and call:

```typescript
import * as user_favorites from "./user_favorites.ts";

// Near other initialize() calls:
user_favorites.initialize({favorites: state_data.favorites});
```

- [ ] **Step 3: Dispatch events**

In `web/src/server_events_dispatch.ts`, add a case in the event-dispatch switch:

```typescript
case "user_favorite":
    user_favorites.handle_event(event);
    break;
```

Add `import * as user_favorites from "./user_favorites.ts";` at the top of the file.

- [ ] **Step 4: Type-check and commit**

```bash
./tools/lint web/src/server_events_dispatch.ts web/src/ui_init.ts web/src/state_data.ts
git add web/src/server_events_dispatch.ts web/src/ui_init.ts web/src/state_data.ts
git commit -m "web: Dispatch user_favorite events into client state."
```

---

## Phase E — Frontend UI

### Task 15: Render the Favorites section in the left sidebar

**Files:**
- Create: `web/src/favorites_list.ts`
- Create: `web/templates/favorites_section.hbs`
- Modify: `web/templates/left_sidebar.hbs`
- Modify: `web/styles/left-sidebar.css`
- Modify: `web/src/stream_list.ts` (call into `favorites_list` to refresh on the same triggers)

> Pattern reference: `web/src/stream_list.ts:856` for stream rendering, `web/src/pm_list.ts` for DM row rendering, and `web/src/stream_list_sort.ts:93` for the pinned-streams section that this one will sit above.

- [ ] **Step 1: Add the template placeholder**

In `web/templates/left_sidebar.hbs`, just above the `#pinned-streams` container, add:

```handlebars
<div id="favorites-section" class="left-sidebar-section">
    <h4 class="left-sidebar-section-header">{{t "Favorites" }}</h4>
    <ul id="favorites-list" class="filters"></ul>
</div>
```

- [ ] **Step 2: Implement the renderer**

Create `web/src/favorites_list.ts`:

```typescript
import $ from "jquery";

import render_favorite_stream_row from "../templates/favorite_stream_row.hbs";
import render_favorite_dm_row from "../templates/favorite_dm_row.hbs";

import * as people from "./people.ts";
import * as pm_conversations from "./pm_conversations.ts";
import * as stream_data from "./stream_data.ts";
import * as sub_store from "./sub_store.ts";
import * as unread from "./unread.ts";
import * as user_favorites from "./user_favorites.ts";

type FavoriteRow =
    | {kind: "stream"; stream_id: number; max_message_id: number; unread: number}
    | {kind: "dm"; user_id: number; max_message_id: number; unread: number};

function build_rows(): FavoriteRow[] {
    const rows: FavoriteRow[] = [];

    for (const stream_id of user_favorites.streams()) {
        const sub = sub_store.get(stream_id);
        if (!sub) continue; // defensive: server should have cleaned up
        rows.push({
            kind: "stream",
            stream_id,
            max_message_id: stream_data.get_latest_message_id(stream_id) ?? 0,
            unread: unread.num_unread_for_stream(stream_id).unmuted_count,
        });
    }

    for (const user_id of user_favorites.users()) {
        const user = people.maybe_get_user_by_id(user_id, true);
        if (!user || !user.is_active) continue;
        const conversation = pm_conversations.recent.get(String(user_id));
        rows.push({
            kind: "dm",
            user_id,
            max_message_id: conversation?.max_message_id ?? 0,
            unread: unread.num_unread_for_user_ids_string(String(user_id)),
        });
    }

    rows.sort((a, b) => b.max_message_id - a.max_message_id);
    return rows;
}

export function update(): void {
    const rows = build_rows();
    const $section = $("#favorites-section");
    if (rows.length === 0) {
        $section.hide();
        return;
    }
    $section.show();
    const html = rows
        .map((r) =>
            r.kind === "stream"
                ? render_favorite_stream_row({
                      sub: sub_store.get(r.stream_id),
                      unread: r.unread,
                  })
                : render_favorite_dm_row({
                      user: people.get_by_user_id(r.user_id),
                      unread: r.unread,
                  }),
        )
        .join("");
    $("#favorites-list").html(html);
}

export function initialize(): void {
    user_favorites.on_change(update);
    update();
}
```

> If `stream_data.get_latest_message_id` does not exist, search for the equivalent helper used by `stream_list.ts` for activity sorting and use that. Same for the DM helper.

- [ ] **Step 3: Add the row templates**

Create `web/templates/favorite_stream_row.hbs`:

```handlebars
<li class="favorite-row stream-row" data-stream-id="{{sub.stream_id}}">
    <a href="#narrow/channel/{{sub.stream_id}}-{{sub.name}}">
        <span class="stream-privacy" style="color: {{sub.color}}">#</span>
        <span class="stream-name">{{sub.name}}</span>
        {{#if unread}}
            <span class="unread-count">{{unread}}</span>
        {{/if}}
    </a>
</li>
```

Create `web/templates/favorite_dm_row.hbs`:

```handlebars
<li class="favorite-row dm-row" data-user-id="{{user.user_id}}">
    <a href="#narrow/dm/{{user.user_id}}-{{user.email}}">
        <span class="user-circle"></span>
        <span class="user-name">{{user.full_name}}</span>
        {{#if unread}}
            <span class="unread-count">{{unread}}</span>
        {{/if}}
    </a>
</li>
```

- [ ] **Step 4: Add scoped CSS**

Append to `web/styles/left-sidebar.css`:

```css
#favorites-section {
    margin-bottom: 0.5em;
}

#favorites-section .left-sidebar-section-header {
    font-size: 0.8125em;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-text-default);
    padding: 0.25em 0.5em;
}

#favorites-list .favorite-row {
    list-style: none;
    padding: 0.25em 0.5em;
}

#favorites-list .favorite-row a {
    display: flex;
    align-items: center;
    gap: 0.5em;
}

#favorites-list .unread-count {
    margin-left: auto;
    font-size: 0.8125em;
    background: var(--color-background-unread);
    border-radius: 0.5em;
    padding: 0 0.5em;
}
```

- [ ] **Step 5: Hook updates into existing triggers**

In `web/src/stream_list.ts`, in any function that re-renders on message arrival or unread change, also call:

```typescript
import * as favorites_list from "./favorites_list.ts";
// ... in appropriate update functions:
favorites_list.update();
```

In `web/src/ui_init.ts`, after `user_favorites.initialize(...)`, also call `favorites_list.initialize()`.

- [ ] **Step 6: Manual smoke check**

Start dev server:
```bash
./tools/run-dev
```

In the browser:
1. Confirm Favorites section is hidden when no favorites.
2. Open the dev console, run a fetch to add one, confirm section appears.
3. Toggle in light + dark theme, confirm CSS works.

- [ ] **Step 7: Commit**

```bash
./tools/lint web/src/favorites_list.ts web/templates/favorite_stream_row.hbs web/templates/favorite_dm_row.hbs web/templates/left_sidebar.hbs web/styles/left-sidebar.css
git add web/src/favorites_list.ts web/templates/favorite_stream_row.hbs web/templates/favorite_dm_row.hbs web/templates/left_sidebar.hbs web/styles/left-sidebar.css web/src/stream_list.ts web/src/ui_init.ts
git commit -m "web: Render Favorites section in left sidebar."
```

---

### Task 16: Add favorite toggle to the channel popover (context menu)

**Files:**
- Modify: `web/src/stream_popover.ts` (or `web/src/popovers/stream_actions_popover.ts` — confirm with `git grep "pin to top"`)
- Modify: `web/templates/popovers/stream_actions_popover.hbs` (or matching template)
- Create: `web/src/favorites.ts` (small module wrapping the API calls)

- [ ] **Step 1: Implement the API client**

Create `web/src/favorites.ts`:

```typescript
import * as channel from "./channel.ts";
import type {FavoriteTarget} from "./user_favorites.ts";

export function add(target: FavoriteTarget): Promise<void> {
    return channel.post({
        url: "/json/users/me/favorites",
        data: {type: target.type, id: target.id},
    });
}

export function remove(target: FavoriteTarget): Promise<void> {
    return channel.del({
        url: `/json/users/me/favorites?type=${target.type}&id=${target.id}`,
    });
}
```

- [ ] **Step 2: Add the menu item**

In the stream-actions popover template, add a row near the existing "Pin to top" entry:

```handlebars
<li class="popover-menu-item" role="menuitem">
    <a class="favorite-channel-toggle" tabindex="0">
        <i class="fa fa-star"></i>
        {{#if is_favorite}}
            {{t "Remove from favorites" }}
        {{else}}
            {{t "Add to favorites" }}
        {{/if}}
    </a>
</li>
```

- [ ] **Step 3: Wire the click handler**

In `web/src/stream_popover.ts`, in the popover's event-binding section:

```typescript
import * as favorites from "./favorites.ts";
import * as user_favorites from "./user_favorites.ts";

// In the click registration:
$popover.on("click", ".favorite-channel-toggle", function (e) {
    e.preventDefault();
    e.stopPropagation();
    const stream_id = $(this).closest("[data-stream-id]").data("stream-id");
    if (user_favorites.is_stream_favorite(stream_id)) {
        favorites.remove({type: "stream", id: stream_id});
    } else {
        favorites.add({type: "stream", id: stream_id});
    }
    popovers.hide_all();
});
```

Pass `is_favorite: user_favorites.is_stream_favorite(stream_id)` into the popover template's render context.

- [ ] **Step 4: Manual test**

Start dev server, right-click a channel in the sidebar, verify menu shows the right label, click toggles the favorite.

- [ ] **Step 5: Commit**

```bash
./tools/lint web/src/favorites.ts web/src/stream_popover.ts web/templates/popovers/stream_actions_popover.hbs
git add web/src/favorites.ts web/src/stream_popover.ts web/templates/popovers/stream_actions_popover.hbs
git commit -m "web: Add favorite toggle to channel context menu."
```

---

### Task 17: Add favorite toggle to the user/DM popover

**Files:**
- Modify: `web/src/user_card_popover.ts` (or `web/src/popovers/user_card_popover.ts`)
- Modify: corresponding `.hbs` template

- [ ] **Step 1: Add the menu item**

Same pattern as Task 16 but in the user card popover template:

```handlebars
{{#unless is_self}}
<li class="popover-menu-item" role="menuitem">
    <a class="favorite-dm-toggle" data-user-id="{{user.user_id}}" tabindex="0">
        <i class="fa fa-star"></i>
        {{#if is_favorite}}
            {{t "Remove from favorites" }}
        {{else}}
            {{t "Add to favorites" }}
        {{/if}}
    </a>
</li>
{{/unless}}
```

- [ ] **Step 2: Wire the handler**

```typescript
$popover.on("click", ".favorite-dm-toggle", function (e) {
    e.preventDefault();
    e.stopPropagation();
    const user_id = Number($(this).data("user-id"));
    if (user_favorites.is_user_favorite(user_id)) {
        favorites.remove({type: "private", id: user_id});
    } else {
        favorites.add({type: "private", id: user_id});
    }
    popovers.hide_all();
});
```

Pass `is_favorite: user_favorites.is_user_favorite(user.user_id)` and `is_self: user.user_id === current_user.user_id` into the template render context.

- [ ] **Step 3: Manual test, lint, commit**

```bash
./tools/lint web/src/user_card_popover.ts web/templates/popovers/user_card_popover.hbs
git add web/src/user_card_popover.ts web/templates/popovers/user_card_popover.hbs
git commit -m "web: Add favorite toggle to user card popover."
```

---

### Task 18: Add favorite toggle to channel info and user info panels

**Files:**
- Modify: `web/src/stream_settings_ui.ts` (or wherever channel settings panel lives — search `git grep "stream-settings"`)
- Modify: corresponding template

- [ ] **Step 1: Add the toggle row in channel settings**

In the channel settings template, near the "Pin to top" toggle, add:

```handlebars
<div class="input-group">
    <label>
        <input type="checkbox" class="favorite-channel-checkbox" {{#if is_favorite}}checked{{/if}}>
        {{t "Show in Favorites" }}
    </label>
</div>
```

In the controller:

```typescript
$panel.on("change", ".favorite-channel-checkbox", function () {
    const stream_id = current_panel_stream_id();
    if ($(this).prop("checked")) {
        favorites.add({type: "stream", id: stream_id});
    } else {
        favorites.remove({type: "stream", id: stream_id});
    }
});
```

- [ ] **Step 2: Add the same toggle in user info panel**

Similar pattern in the user info modal/panel. Use `{type: "private", id: user_id}`.

- [ ] **Step 3: Lint, manually verify, commit**

```bash
./tools/lint <files>
git add <files>
git commit -m "web: Add favorite toggle to channel and user info panels."
```

---

## Phase F — End-User Documentation

### Task 19: Help center article

**Files:**
- Create: `starlight_help/src/content/docs/favorites.mdx`
- Create: `starlight_help/src/images/favorites-section.png` (screenshot)
- Modify: `starlight_help/astro.config.mjs` (sidebar entry)

- [ ] **Step 1: Write the article**

Create `starlight_help/src/content/docs/favorites.mdx`:

```mdx
---
title: Favorite channels and direct messages
---

import {Steps} from "@astrojs/starlight/components";

You can mark channels and direct message conversations you use most as
**favorites**. Favorites appear in a dedicated **Favorites** section at the
top of the left sidebar, sorted by the most recent activity, so the
conversations you care about are always one click away.

Favorites are a separate concept from
[pinned channels](/help/pin-a-channel-to-the-top): a channel can be
favorited, pinned, both, or neither.

## Add a channel to favorites

<Steps>

1. Right-click the channel in the left sidebar.
2. Click **Add to favorites**.

</Steps>

You can also toggle this from the channel's settings panel.

## Add a direct message conversation to favorites

<Steps>

1. Open the user's profile card by clicking their name.
2. Click **Add to favorites**.

</Steps>

Group direct messages cannot currently be added to favorites.

## Remove a favorite

Use the same menu item — it changes to **Remove from favorites** when the
channel or DM is already a favorite.

Favorites are removed automatically when:

* You unsubscribe from a favorited channel.
* A favorited channel is archived by an administrator.
* A user you have favorited as a DM is deactivated.
```

- [ ] **Step 2: Take screenshot for the article**

Run dev server, set up a few favorites, take a screenshot of the sidebar in light theme. Save as `starlight_help/src/images/favorites-section.png`. Optionally add `<img src={favorites-section.png} alt="..." />` reference in the MDX.

- [ ] **Step 3: Add sidebar entry**

In `starlight_help/astro.config.mjs`, add an entry under the appropriate group (probably "Reading channels" or similar):

```javascript
{label: "Favorite channels and DMs", slug: "favorites"},
```

- [ ] **Step 4: Build and verify**

Run the help-center dev build (consult `docs/documentation/helpcenter.md` for the exact command if unsure) and visually verify the page renders.

- [ ] **Step 5: Commit**

```bash
git add starlight_help/src/content/docs/favorites.mdx starlight_help/src/images/favorites-section.png starlight_help/astro.config.mjs
git commit -m "help: Document the favorites feature."
```

---

## Phase G — Final Verification

### Task 20: Visual + manual end-to-end test

- [ ] **Step 1: Run all backend tests**

```bash
./tools/test-backend zerver.tests.test_user_favorites
./tools/test-backend zerver.openapi
```

Expected: all green.

- [ ] **Step 2: Run web tests**

```bash
./tools/test-js-with-node web/tests/user_favorites.test.cjs
```

- [ ] **Step 3: Full lint**

```bash
./tools/lint
```

Expected: clean.

- [ ] **Step 4: Manual UI checklist (per CLAUDE.md "Manual Testing for UI Changes")**

Use the visual-test skill to take before/after screenshots in light + dark theme. Verify:

- Favorites section hidden when empty.
- Mixed channel + DM rows render correctly.
- Sorting by most recent activity works (post a message in a non-top favorite, observe re-sort).
- Right-click menu items show correct labels (Add vs Remove).
- Channel settings and user info toggles work.
- Section header unread count, if implemented, matches per-row counts.
- Two-tab sync: toggle in tab A, observe update in tab B.
- Long channel names and long DM partner names do not break layout.
- Narrow viewport (480 px) — no overflow.
- Translation: temporarily set the user's language to a non-English locale, verify strings are translated (if catalog updated).

- [ ] **Step 5: Cleanup-path verification**

Manually:
1. Favorite a channel, then unsubscribe → favorite disappears, no console errors.
2. Favorite a DM, then deactivate the partner via admin panel → favorite disappears.
3. Favorite a channel, then have admin archive it → favorite disappears.

- [ ] **Step 6: Final commit if any tweaks needed, then done**

```bash
git status   # Should be clean
git log --oneline upstream/main..HEAD   # Review all commits in the branch
```

Open a PR following the [CLAUDE.md](../../.claude/CLAUDE.md) PR-description guidelines, prefixed with `[ai]`.

---

## Self-review notes (for future maintenance)

- **Hooks audit:** if Zulip later introduces a new code path that revokes channel access (e.g. group-based permission removal), add a `do_remove_user_favorites_for_recipient` call there.
- **Group DM support:** lifting the rejection of `DIRECT_MESSAGE_GROUP` is a one-line change in `_resolve_recipient`, plus a third branch in `_favorite_payload` and the frontend renderer.
- **Manual reorder:** add an `order` int column to `UserFavorite` and a reorder endpoint; frontend sort key changes from `max_message_id` to `order`.
