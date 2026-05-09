from zerver.models import Recipient, UserFavorite, UserProfile
from zerver.models.recipients import bulk_get_direct_message_group_user_ids


def get_user_favorites(user_profile: UserProfile) -> list[dict[str, object]]:
    """Return the user's favorite targets in wire format.

    Each entry is either {"type": "channel", "id": stream_id} or
    {"type": "dm", "user_ids": [...]} where user_ids excludes the
    requesting user.
    """
    rows = list(
        UserFavorite.objects.filter(user_profile=user_profile)
        .select_related("recipient")
        .values_list("recipient__type", "recipient__type_id", "recipient_id")
    )

    dm_recipient_ids = [
        rid for rtype, _tid, rid in rows if rtype == Recipient.DIRECT_MESSAGE_GROUP
    ]
    dm_users = (
        bulk_get_direct_message_group_user_ids(dm_recipient_ids)
        if dm_recipient_ids
        else {}
    )

    out: list[dict[str, object]] = []
    for rtype, type_id, recipient_id in rows:
        if rtype == Recipient.STREAM:
            out.append({"type": "channel", "id": type_id})
        elif rtype == Recipient.DIRECT_MESSAGE_GROUP:
            other_ids = sorted(
                uid for uid in dm_users.get(recipient_id, set()) if uid != user_profile.id
            )
            out.append({"type": "dm", "user_ids": other_ids})
    return out
