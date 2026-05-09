from django.db import models
from django.db.models import CASCADE
from django.utils.timezone import now as timezone_now

from zerver.models.recipients import Recipient
from zerver.models.users import UserProfile


class UserFavorite(models.Model):
    """A user's favorited channel or 1-1 DM target.

    The favorited target is identified by a Recipient row, supporting:
      * Recipient.STREAM              -> a channel the user is subscribed to
      * Recipient.DIRECT_MESSAGE_GROUP -> a DM, restricted to group_size == 2
        (1-1 DMs only) by the view layer.

    Group DMs (group_size >= 3) are rejected at the view layer for now.
    Cleanup hooks delete rows when the target becomes inaccessible.
    """

    user_profile = models.ForeignKey(UserProfile, on_delete=CASCADE)
    recipient = models.ForeignKey(Recipient, on_delete=CASCADE)
    created_at = models.DateTimeField(default=timezone_now)

    class Meta:
        unique_together = ("user_profile", "recipient")
        indexes = [models.Index(fields=["user_profile"])]
