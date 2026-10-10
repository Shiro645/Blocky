"""Hide the staff commands from players.

Discord lets a bot hide a command behind a permission ("default member
permissions"), not behind a role. So at startup the bot picks a permission that
the staff role has and @everyone doesn't: members without it don't even see the
staff commands in the list. Who may *use* them is still decided by the staff
role (utils/checks.staff_only). Admins can fine-tune it per role in
Server Settings → Integrations → Blocky.
"""
from __future__ import annotations

# Permissions only staff usually have, the most common for moderators first.
CANDIDATES = (
    "moderate_members", "kick_members", "ban_members", "manage_messages", "manage_nicknames",
    "manage_roles", "manage_channels", "manage_guild", "administrator",
)


def pick(staff: set[str] | None, everyone: set[str]) -> str | None:
    """The permission that hides the staff commands, or None when no permission fits
    (they then stay visible to everyone).

    `staff` holds the permission names of the staff role; None when no staff role is
    set, staff are then the members who can manage the server.
    """
    if staff is None:
        return "manage_guild"
    for name in CANDIDATES:
        if name in staff and name not in everyone:
            return name
    return None
