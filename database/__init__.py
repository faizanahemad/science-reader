"""
SQLite/persistence layer.

This package will host all DB and persistence helpers currently defined in the
monolithic `server.py`. Endpoint modules should import from `database.*` instead
of manipulating SQLite directly.

During the refactor rollout, modules are introduced incrementally and this
package may initially export only a subset of functions.
"""

from __future__ import annotations

from database import connection as connection
from database import conversations as conversations
from database import doubts as doubts
from database import sections as sections
from database import users as users
from database import workspaces as workspaces

# ---------------------------------------------------------------------------
# Connection / schema
# ---------------------------------------------------------------------------
from database.connection import create_connection, create_tables

# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
from database.conversations import (
    addConversation,
    checkConversationExists,
    cleanup_deleted_conversations,
    getAllCoversations,
    getCoversationsForUser,
    getConversationById,
    removeUserFromConversation,
    deleteConversationForUser,
)
from database.conversations import configure_users_dir as configure_conversations_users_dir

# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------
from database.workspaces import (
    addConversationToWorkspace,
    collapseWorkspaces,
    createWorkspace,
    deleteWorkspace,
    getConversationsForWorkspace,
    getWorkspaceForConversation,
    load_workspaces_for_user,
    moveConversationToWorkspace,
    removeConversationFromWorkspace,
    updateWorkspace,
)

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
from database.users import (
    addUserToUserDetailsTable,
    getUserFromUserDetailsTable,
    updateUserInfoInUserDetailsTable,
)
from database.users import configure_users_dir as configure_users_users_dir

# ---------------------------------------------------------------------------
# Doubts
# ---------------------------------------------------------------------------
from database.doubts import (
    add_doubt,
    build_doubt_tree,
    delete_doubt,
    get_doubt,
    get_doubt_children,
    get_doubt_history,
    get_doubts_for_message,
)
from database.doubts import configure_users_dir as configure_doubts_users_dir

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
from database.sections import bulk_update_section_hidden_detail, get_section_hidden_details
from database.sections import configure_users_dir as configure_sections_users_dir


def configure_users_dir(users_dir: str) -> None:
    """
    Configure default `users_dir` for DB helper modules that support it.

    Why this exists
    ---------------
    During the incremental refactor, some DB modules support an optional
    `users_dir=None` argument that falls back to a configured default. This
    helper sets that default for all such modules so callers can do it once at
    startup.
    """

    configure_conversations_users_dir(users_dir)
    configure_users_users_dir(users_dir)
    configure_doubts_users_dir(users_dir)
    configure_sections_users_dir(users_dir)


__all__ = [
    # Submodules
    "connection",
    "conversations",
    "workspaces",
    "users",
    "doubts",
    "sections",
    # Global configuration
    "configure_users_dir",
    "configure_conversations_users_dir",
    "configure_users_users_dir",
    "configure_doubts_users_dir",
    "configure_sections_users_dir",
    # Connection / schema
    "create_connection",
    "create_tables",
    # Conversations
    "addConversation",
    "checkConversationExists",
    "getCoversationsForUser",
    "deleteConversationForUser",
    "cleanup_deleted_conversations",
    "getAllCoversations",
    "getConversationById",
    "removeUserFromConversation",
    # Workspaces
    "load_workspaces_for_user",
    "addConversationToWorkspace",
    "moveConversationToWorkspace",
    "removeConversationFromWorkspace",
    "getWorkspaceForConversation",
    "getConversationsForWorkspace",
    "createWorkspace",
    "collapseWorkspaces",
    "updateWorkspace",
    "deleteWorkspace",
    # Users
    "addUserToUserDetailsTable",
    "getUserFromUserDetailsTable",
    "updateUserInfoInUserDetailsTable",
    # Doubts
    "add_doubt",
    "delete_doubt",
    "get_doubt",
    "get_doubt_children",
    "build_doubt_tree",
    "get_doubts_for_message",
    "get_doubt_history",
    # Sections
    "get_section_hidden_details",
    "bulk_update_section_hidden_detail",
]


