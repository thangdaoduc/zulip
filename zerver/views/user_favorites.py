from typing import Literal

from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from pydantic import Json

from zerver.actions.user_favorites import (
    do_add_user_favorite,
    do_remove_user_favorite,
)
from zerver.lib.exceptions import JsonableError
from zerver.lib.response import json_success
from zerver.lib.streams import access_stream_by_id
from zerver.lib.typed_endpoint import typed_endpoint
from zerver.lib.users import access_user_by_id
from zerver.models import Recipient, UserProfile
from zerver.models.recipients import get_or_create_direct_message_group


def _resolve_favorite_recipient(
    user_profile: UserProfile,
    fav_type: str,
    channel_id: int | None,
    user_ids: list[int] | None,
) -> Recipient:
    if fav_type == "channel":
        if channel_id is None:
            raise JsonableError(_("Missing 'id' for channel favorite"))
        stream, sub = access_stream_by_id(
            user_profile,
            channel_id,
            require_active_channel=True,
            require_content_access=True,
        )
        if sub is None:
            raise JsonableError(_("Not subscribed to this channel"))
        return stream.recipient

    if fav_type == "dm":
        if not user_ids:
            raise JsonableError(_("Missing 'user_ids' for DM favorite"))
        if len(user_ids) != 1:
            raise JsonableError(
                _("Only 1-1 DM favorites are supported (provide exactly one other user_id)")
            )
        other_id = user_ids[0]
        if other_id == user_profile.id:
            raise JsonableError(_("Cannot favorite a DM with yourself"))
        # Validates same realm + active.
        access_user_by_id(
            user_profile, other_id, allow_bots=True, for_admin=False
        )
        dmg = get_or_create_direct_message_group(
            sorted([user_profile.id, other_id])
        )
        assert dmg.recipient is not None
        return dmg.recipient

    raise JsonableError(
        _("Invalid favorite type: {fav_type}").format(fav_type=fav_type)
    )


@typed_endpoint
def add_favorite(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    type: Literal["channel", "dm"],
    id: Json[int] | None = None,
    user_ids: Json[list[int]] | None = None,
) -> HttpResponse:
    recipient = _resolve_favorite_recipient(user_profile, type, id, user_ids)
    do_add_user_favorite(user_profile, recipient, acting_user=user_profile)
    return json_success(request)


@typed_endpoint
def remove_favorite(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    type: Literal["channel", "dm"],
    id: Json[int] | None = None,
    user_ids: Json[list[int]] | None = None,
) -> HttpResponse:
    recipient = _resolve_favorite_recipient(user_profile, type, id, user_ids)
    do_remove_user_favorite(user_profile, recipient, acting_user=user_profile)
    return json_success(request)
