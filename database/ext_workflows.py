"""
Database helpers for extension workflows.

Provides CRUD operations for the ``ExtensionWorkflows`` table in ``users.db``.
Ported from ``extension.py`` ExtensionDB workflow methods to run on the main
backend so the Chrome extension can manage workflows without a separate server.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from sqlite3 import Error
from typing import Any, Dict, List, Optional

from database.connection import create_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row → dict conversion
# ---------------------------------------------------------------------------


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    """Convert a raw DB row (6-tuple) to a typed workflow dict."""
    return {
        "workflow_id": row[0],
        "user_email": row[1],
        "name": row[2],
        "steps": json.loads(row[3]) if row[3] else [],
        "created_at": row[4],
        "updated_at": row[5],
    }


# ---------------------------------------------------------------------------
# DB helper class
# ---------------------------------------------------------------------------


class ExtWorkflowsDB:
    """
    CRUD helper for the ``ExtensionWorkflows`` table.

    Parameters
    ----------
    db_path : str
        Absolute path to ``users.db``.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _conn(self):
        return create_connection(self.db_path)

    def create_workflow(
        self, user_email: str, name: str, steps: List[Dict]
    ) -> Dict[str, Any]:
        """
        Create a new multi-step prompt workflow.

        Parameters
        ----------
        user_email : str
        name : str
            Workflow display name.
        steps : list[dict]
            Each step has ``{title: str, prompt: str}``.

        Returns
        -------
        dict
            The newly created workflow record.
        """
        conn = self._conn()
        cursor = conn.cursor()
        workflow_id = secrets.token_hex(16)
        now = datetime.utcnow().isoformat()

        try:
            cursor.execute(
                """
                INSERT INTO ExtensionWorkflows
                (workflow_id, user_email, name, steps_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (workflow_id, user_email, name, json.dumps(steps), now, now),
            )
            conn.commit()
            return {
                "workflow_id": workflow_id,
                "user_email": user_email,
                "name": name,
                "steps": steps,
                "created_at": now,
                "updated_at": now,
            }
        except Error as e:
            raise RuntimeError(f"Failed to create workflow: {e}") from e
        finally:
            conn.close()

    def get_workflow(
        self, user_email: str, workflow_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a single workflow by ID (scoped to user).

        Parameters
        ----------
        user_email : str
        workflow_id : str

        Returns
        -------
        dict or None
        """
        conn = self._conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT workflow_id, user_email, name, steps_json, "
                "created_at, updated_at "
                "FROM ExtensionWorkflows "
                "WHERE workflow_id = ? AND user_email = ?",
                (workflow_id, user_email),
            )
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None
        except Error as e:
            raise RuntimeError(f"Failed to get workflow: {e}") from e
        finally:
            conn.close()

    def list_workflows(self, user_email: str) -> List[Dict[str, Any]]:
        """
        List all workflows for a user, newest first.

        Parameters
        ----------
        user_email : str

        Returns
        -------
        list[dict]
        """
        conn = self._conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT workflow_id, user_email, name, steps_json, "
                "created_at, updated_at "
                "FROM ExtensionWorkflows "
                "WHERE user_email = ? ORDER BY updated_at DESC",
                (user_email,),
            )
            return [_row_to_dict(row) for row in cursor.fetchall()]
        except Error as e:
            raise RuntimeError(f"Failed to list workflows: {e}") from e
        finally:
            conn.close()

    def update_workflow(
        self,
        user_email: str,
        workflow_id: str,
        name: str,
        steps: List[Dict],
    ) -> bool:
        """
        Replace a workflow's name and steps.

        Parameters
        ----------
        user_email : str
        workflow_id : str
        name : str
        steps : list[dict]

        Returns
        -------
        bool
            True if a row was actually updated.
        """
        conn = self._conn()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        try:
            cursor.execute(
                "UPDATE ExtensionWorkflows "
                "SET name = ?, steps_json = ?, updated_at = ? "
                "WHERE workflow_id = ? AND user_email = ?",
                (name, json.dumps(steps), now, workflow_id, user_email),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            raise RuntimeError(f"Failed to update workflow: {e}") from e
        finally:
            conn.close()

    def delete_workflow(self, user_email: str, workflow_id: str) -> bool:
        """
        Delete a workflow.

        Parameters
        ----------
        user_email : str
        workflow_id : str

        Returns
        -------
        bool
            True if a row was deleted.
        """
        conn = self._conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM ExtensionWorkflows "
                "WHERE workflow_id = ? AND user_email = ?",
                (workflow_id, user_email),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            raise RuntimeError(f"Failed to delete workflow: {e}") from e
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def get_ext_workflows_db() -> ExtWorkflowsDB:
    """
    Return an ``ExtWorkflowsDB`` pointing at the main backend's ``users.db``.
    """
    from endpoints.state import get_state

    state = get_state()
    db_path = os.path.join(state.users_dir, "users.db")
    return ExtWorkflowsDB(db_path)
