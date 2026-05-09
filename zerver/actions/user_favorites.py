from django.db import transaction
from django.utils.timezone import now as timezone_now

from zerver.models import Recipient, UserFavorite, UserProfile
from zerver.models.realm_audit_logs import AuditLogEventType, RealmAuditLog
from zerver.models.recipients import (
    bulk_get_direct_message_group_user_ids,
    get_direct_message_group_user_ids,
)
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


def _bulk_remove_favorites(
    rows: list[tuple[int, int, int, int]],
) -> None:
    """Delete the given UserFavorite rows in bulk and emit per-user events.

    Each row is (favorite_id, user_profile_id, recipient_id, recipient_type).
    Caller is responsible for being inside a transaction.
    """
    if not rows:
        return

    favorite_ids = [r[0] for r in rows]
    UserFavorite.objects.filter(id__in=favorite_ids).delete()

    # Group by user so we can fetch each user once.
    user_ids = {r[1] for r in rows}
    users_by_id = {u.id: u for u in UserProfile.objects.filter(id__in=user_ids)}

    # For DM rows, fetch participant lists in bulk.
    dm_recipient_ids = [
        r[2] for r in rows if r[3] == Recipient.DIRECT_MESSAGE_GROUP
    ]
    dm_users = (
        bulk_get_direct_message_group_user_ids(dm_recipient_ids)
        if dm_recipient_ids
        else {}
    )

    audit_event_time = timezone_now()
    audit_logs: list[RealmAuditLog] = []

    # Group events by realm to share send_event_on_commit calls.
    per_user_events: dict[int, dict[str, object]] = {}
    for _fav_id, user_profile_id, recipient_id, recipient_type in rows:
        user = users_by_id[user_profile_id]
        if recipient_type == Recipient.STREAM:
            # type_id is stream id; we have to look it up from Recipient.
            payload: dict[str, object] = {
                "type": "channel",
                "id": Recipient.objects.get(id=recipient_id).type_id,
            }
        else:
            other_ids = sorted(
                uid for uid in dm_users.get(recipient_id, set()) if uid != user.id
            )
            payload = {"type": "dm", "user_ids": other_ids}

        audit_logs.append(
            RealmAuditLog(
                realm=user.realm,
                modified_user=user,
                event_type=AuditLogEventType.USER_FAVORITE_REMOVED,
                event_time=audit_event_time,
                extra_data={
                    "recipient_id": recipient_id,
                    "recipient_type": recipient_type,
                },
            )
        )

        per_user_events[user_profile_id] = {
            "type": "user_favorite",
            "op": "remove",
            "favorite": payload,
        }

    RealmAuditLog.objects.bulk_create(audit_logs)
    for user_profile_id, event in per_user_events.items():
        user = users_by_id[user_profile_id]
        send_event_on_commit(user.realm, event, [user.id])


def remove_favorites_for_user_stream_pairs(
    pairs: list[tuple[int, int]],
) -> None:
    """Delete favorites where (user_profile_id, stream_recipient_id) match.

    Used by stream-unsubscribe cleanup.
    """
    if not pairs:
        return

    user_ids = {u for u, _r in pairs}
    recipient_ids = {r for _u, r in pairs}
    pair_set = set(pairs)

    candidates = list(
        UserFavorite.objects.filter(
            user_profile_id__in=user_ids, recipient_id__in=recipient_ids
        ).values_list("id", "user_profile_id", "recipient_id", "recipient__type")
    )
    rows = [
        (fav_id, uid, rid, rtype)
        for fav_id, uid, rid, rtype in candidates
        if (uid, rid) in pair_set
    ]
    _bulk_remove_favorites(rows)


def remove_favorites_for_recipient(recipient: Recipient) -> None:
    """Delete all favorites pointing at this recipient (for any user)."""
    rows = list(
        UserFavorite.objects.filter(recipient=recipient).values_list(
            "id", "user_profile_id", "recipient_id", "recipient__type"
        )
    )
    _bulk_remove_favorites(rows)


def remove_all_favorites_of_user(user_profile: UserProfile) -> None:
    """Delete all favorites owned by this user (e.g. on deactivation).

    No events are emitted: the user is being deactivated and their event
    queues are torn down.
    """
    rows = list(
        UserFavorite.objects.filter(user_profile=user_profile).values_list(
            "id", "recipient_id", "recipient__type"
        )
    )
    if not rows:
        return

    UserFavorite.objects.filter(user_profile=user_profile).delete()

    audit_event_time = timezone_now()
    RealmAuditLog.objects.bulk_create(
        [
            RealmAuditLog(
                realm=user_profile.realm,
                modified_user=user_profile,
                event_type=AuditLogEventType.USER_FAVORITE_REMOVED,
                event_time=audit_event_time,
                extra_data={"recipient_id": rid, "recipient_type": rtype},
            )
            for _fav_id, rid, rtype in rows
        ]
    )
