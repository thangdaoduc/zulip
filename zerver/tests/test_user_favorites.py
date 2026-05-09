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
