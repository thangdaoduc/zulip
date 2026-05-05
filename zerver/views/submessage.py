import time
from typing import Any

import orjson
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from pydantic import Json

from zerver.actions.submessage import do_add_submessage, verify_submessage_sender
from zerver.lib.exceptions import JsonableError
from zerver.lib.message import access_message
from zerver.lib.response import json_success
from zerver.lib.typed_endpoint import typed_endpoint
from zerver.lib.validator import validate_poll_data, validate_todo_data
from zerver.lib.widget import get_widget_type
from zerver.models import SubMessage, UserProfile


def get_poll_state(message_id: int) -> dict[str, Any]:
    """Read poll state from the widget submessage (id=first).

    The is_closed flag is stored in the widget submessage's extra_data,
    updated atomically when close/open ops are processed. This gives O(1)
    lookups regardless of how many vote/new_option submessages exist.
    """
    first = SubMessage.objects.filter(
        message_id=message_id,
        msg_type="widget",
    ).order_by("id").first()

    if first is None:
        return {"is_closed": False, "allow_new_options": True}

    data = orjson.loads(first.content)
    extra = data.get("extra_data", {})
    return {
        "is_closed": extra.get("is_closed", False),
        "allow_new_options": extra.get("allow_new_options", True),
    }


def _update_poll_closed_flag(message_id: int, is_closed: bool) -> None:
    """Update the is_closed flag in the widget submessage's extra_data.

    Must be called within the same transaction as do_add_submessage so
    the flag is visible to subsequent requests.
    """
    first = SubMessage.objects.filter(
        message_id=message_id,
        msg_type="widget",
    ).order_by("id").first()

    if first:
        data = orjson.loads(first.content)
        extra = data.setdefault("extra_data", {})
        extra["is_closed"] = is_closed
        first.content = orjson.dumps(data).decode()
        first.save(update_fields=["content"])


# transaction.atomic is required since we use FOR UPDATE queries in access_message.
@transaction.atomic(durable=True)
@typed_endpoint
def process_submessage(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    content: str,
    message_id: Json[int],
    msg_type: str,
) -> HttpResponse:
    message = access_message(user_profile, message_id, lock_message=True, is_modifying_message=True)

    verify_submessage_sender(
        message_id=message.id,
        message_sender_id=message.sender_id,
        submessage_sender_id=user_profile.id,
    )

    try:
        widget_data = orjson.loads(content)
    except orjson.JSONDecodeError:
        raise JsonableError(_("Invalid json for submessage"))

    widget_type = get_widget_type(message_id=message.id)

    is_widget_author = message.sender_id == user_profile.id

    assert isinstance(widget_data, dict)
    op_type = widget_data.get("type")

    if widget_type == "poll":
        poll_state = get_poll_state(message_id=message.id)

        if poll_state["is_closed"] and op_type in ("vote", "new_option"):
            raise JsonableError(_("This poll is closed."))

        if (
            not poll_state["allow_new_options"]
            and op_type == "new_option"
            and not is_widget_author
        ):
            raise JsonableError(_("This poll does not allow new options."))

        try:
            validate_poll_data(poll_data=widget_data, is_widget_author=is_widget_author)
        except ValidationError as error:
            raise JsonableError(error.message)

        if op_type == "close":
            _update_poll_closed_flag(message.id, True)
        elif op_type == "open":
            _update_poll_closed_flag(message.id, False)

    if widget_type == "todo":
        try:
            validate_todo_data(todo_data=widget_data, is_widget_author=is_widget_author)
        except ValidationError as error:
            raise JsonableError(error.message)

    widget_data["timestamp"] = time.time()
    content = orjson.dumps(widget_data).decode()

    do_add_submessage(
        realm=user_profile.realm,
        sender_id=user_profile.id,
        message_id=message.id,
        msg_type=msg_type,
        content=content,
    )
    return json_success(request)
