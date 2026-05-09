from django.db import transaction
from django.utils.timezone import now as timezone_now

from zerver.models import Recipient, UserFavorite, UserProfile
from zerver.models.realm_audit_logs import AuditLogEventType, RealmAuditLog
from zerver.models.recipients import get_direct_message_group_user_ids
from zerver.tornado.django_api import send_event_on_commit


def favorite_payload_for_user(
    recipient: Recipient, user_profile: UserProfile
) -> dict[str, object]:
    """Translate a Recipient into the wire shape clients consume.

    For DMs the wire format lists the *other* participants, so this is
    computed relative to the requesting/receiving user.
    """
    if recipient.type == Recipient.STREAM:
        return {"type": "channel", "id": recipient.type_id}
    if recipient.type == Recipient.DIRECT_MESSAGE_GROUP:
        other_ids = sorted(
            uid
            for uid in get_direct_message_group_user_ids(recipient)
            if uid != user_profile.id
        )
        return {"type": "dm", "user_ids": other_ids}
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
            "favorite": favorite_payload_for_user(recipient, user_profile),
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
            "favorite": favorite_payload_for_user(recipient, user_profile),
        },
        [user_profile.id],
    )
