"""Hide the staff commands from players.

Discord lets a bot hide a command behind a permission ("default member
permissions"), not behind a role. So at startup the bot picks a permission that
the staff role has and **no other role** has (roles of other bots and admin roles
aside: admins see every command anyway): members without it don't even see the
staff commands in the list. Who may *use* them is still decided by the staff role
(utils/checks.staff_only). When no permission fits, the commands are hidden behind
Administrator: then give the staff role a permission only it has (e.g. Timeout
Members), or allow the staff role in Server Settings → Integrations → Blocky.
"""
from __future__ import annotations

# Permissions only staff usually have, the most common for moderators first.
CANDIDATES = (
    "moderate_members", "kick_members", "ban_members", "manage_messages", "manage_nicknames", "view_audit_log",
    "mute_members", "move_members", "deafen_members", "manage_threads", "manage_events", "manage_webhooks",
    "manage_roles", "manage_channels", "manage_guild", "administrator",
)
FALLBACK = "administrator"


def pick(staff: set[str] | None, others: list[set[str]]) -> tuple[str, bool]:
    """(the permission that hides the staff commands, whether it fits).

    `staff`: the permission names of the staff role (None when no staff role is set:
    staff are then the administrators). `others`: the permission names of every other
    role that matters, @everyone included. When nothing fits, (Administrator, False).
    """
    if staff is None:
        return FALLBACK, True
    taken = set().union(*others) if others else set()
    for name in CANDIDATES:
        if name in staff and name not in taken:
            return name, True
    return FALLBACK, False
