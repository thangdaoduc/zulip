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
        from zerver.models import Stream
        stream = Stream.objects.get(id=recipient.type_id)

        with self.capture_send_event_calls(expected_num_events=1) as events:
            do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        event = events[0]["event"]
        self.assertEqual(event["type"], "user_favorite")
        self.assertEqual(event["op"], "add")
        self.assertEqual(event["favorite"], {"type": "channel", "id": stream.id})
        self.assertEqual(events[0]["users"], [hamlet.id])

    def test_add_dm_favorite_sends_event_with_user_ids(self) -> None:
        from zerver.models.recipients import get_or_create_direct_message_group

        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        dmg = get_or_create_direct_message_group(sorted([hamlet.id, cordelia.id]))
        recipient = dmg.recipient
        assert recipient is not None

        with self.capture_send_event_calls(expected_num_events=1) as events:
            do_add_user_favorite(hamlet, recipient, acting_user=hamlet)

        self.assertEqual(
            events[0]["event"]["favorite"],
            {"type": "dm", "user_ids": [cordelia.id]},
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


class UserFavoriteViewTest(ZulipTestCase):
    def test_post_channel_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream

        stream = Stream.objects.get(name="Verona", realm=hamlet.realm)

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "channel", "id": stream.id},
)
        self.assert_json_success(result)
        self.assertEqual(
            UserFavorite.objects.filter(
                user_profile=hamlet,
                recipient=stream.recipient,
            ).count(),
            1,
        )

    def test_post_dm_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "dm", "user_ids": orjson_dumps([cordelia.id])},
)
        self.assert_json_success(result)
        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 1)

    def test_post_rejects_unsubscribed_channel(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        # Stream that hamlet is not subscribed to.
        stream = self.make_stream("OnlyCordelia", invite_only=True)
        self.subscribe(cordelia, "OnlyCordelia")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "channel", "id": stream.id},
        )
        self.assert_json_error(result, "Invalid channel ID")

    def test_post_rejects_self_user(self) -> None:
        hamlet = self.example_user("hamlet")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "dm", "user_ids": orjson_dumps([hamlet.id])},
)
        self.assert_json_error(result, "Cannot favorite a DM with yourself")

    def test_post_rejects_group_dm(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        othello = self.example_user("othello")

        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "dm", "user_ids": orjson_dumps([cordelia.id, othello.id])},
)
        self.assert_json_error(
            result,
            "Only 1-1 DM favorites are supported (provide exactly one other user_id)",
        )

    def test_post_rejects_invalid_type(self) -> None:
        hamlet = self.example_user("hamlet")
        result = self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "group", "id": 1},
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
                    {"type": "channel", "id": stream_id},
                )
            )
        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 1)

    def test_delete_removes_channel_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        self.subscribe(hamlet, "Verona")
        from zerver.models import Stream

        stream_id = Stream.objects.get(name="Verona", realm=hamlet.realm).id

        self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "channel", "id": stream_id},
)
        result = self.api_delete(
            hamlet,
            f"/api/v1/users/me/favorites?type=channel&id={stream_id}",
        )
        self.assert_json_success(result)
        self.assertEqual(UserFavorite.objects.filter(user_profile=hamlet).count(), 0)

    def test_delete_removes_dm_favorite(self) -> None:
        hamlet = self.example_user("hamlet")
        cordelia = self.example_user("cordelia")
        self.api_post(
            hamlet,
            "/api/v1/users/me/favorites",
            {"type": "dm", "user_ids": orjson_dumps([cordelia.id])},
)
        result = self.api_delete(
            hamlet,
            f"/api/v1/users/me/favorites?type=dm&user_ids=[{cordelia.id}]",
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
            f"/api/v1/users/me/favorites?type=channel&id={stream_id}",
        )
        self.assert_json_success(result)


def orjson_dumps(value: object) -> str:
    import orjson

    return orjson.dumps(value).decode()
