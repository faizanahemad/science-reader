"""
Extension Backend Module

This module provides backend support for the Chrome extension, including:
- Token-based authentication (JWT)
- Extension-specific conversation management
- Separate conversation storage from web UI

All extension-specific logic is contained here to avoid modifying core modules.
The extension shares prompts, memories (PKB), and user accounts with the web UI,
but has separate conversation storage.

Usage:
    from extension import ExtensionAuth, ExtensionDB, ExtensionConversation
"""

import os
import json
import secrets
import sqlite3
from sqlite3 import Error
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Dict, Any, Tuple
from flask import request, jsonify
from queue import Queue

# Import existing modules (direct reuse)
from call_llm import CallLLm


def create_connection(db_file):
    """
    Create a database connection to a SQLite database.

    This is a local copy to avoid circular imports with server.py.

    Args:
        db_file: Path to the SQLite database file

    Returns:
        sqlite3.Connection or None if connection fails
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        print(f"Database connection error: {e}")
    return conn


# =============================================================================
# Configuration
# =============================================================================

# JWT configuration
# In production, use environment variable: os.getenv("EXTENSION_JWT_SECRET")
JWT_SECRET = os.getenv("EXTENSION_JWT_SECRET", secrets.token_hex(32))
TOKEN_EXPIRY_HOURS = 24 * 7  # 7 days

# Extension storage paths (will be set by server.py)
_extension_db_path = None
_extension_conv_folder = None


def init_extension_paths(users_dir: str, conversation_folder: str):
    """
    Initialize extension storage paths.
    Called from server.py after users_dir is set.

    Args:
        users_dir: Path to users directory (e.g., "./users")
        conversation_folder: Path to main conversation folder
    """
    global _extension_db_path, _extension_conv_folder
    _extension_db_path = os.path.join(users_dir, "extension.db")
    _extension_conv_folder = os.path.join(conversation_folder, "extension")
    os.makedirs(_extension_conv_folder, exist_ok=True)


def get_extension_db_path() -> str:
    """Get the extension database path."""
    if _extension_db_path is None:
        raise RuntimeError(
            "Extension paths not initialized. Call init_extension_paths() first."
        )
    return _extension_db_path


def get_extension_conv_folder() -> str:
    """Get the extension conversation folder path."""
    if _extension_conv_folder is None:
        raise RuntimeError(
            "Extension paths not initialized. Call init_extension_paths() first."
        )
    return _extension_conv_folder


# =============================================================================
# ExtensionAuth - Token-based authentication
# =============================================================================


class ExtensionAuth:
    """
    Token-based authentication for Chrome extension.

    Why JWT instead of Flask sessions:
    - Chrome extensions cannot reliably use Flask session cookies
    - Extensions have different origin than the server
    - Service workers have limitations with cookies
    - JWT tokens can be stored in chrome.storage and sent in headers

    Usage:
        # Generate token on login
        token = ExtensionAuth.generate_token(user_email)

        # Protect endpoints
        @ExtensionAuth.require_ext_auth
        def my_endpoint():
            email = request.ext_user_email  # Available in request context
    """

    @staticmethod
    def generate_token(user_email: str) -> str:
        """
        Generate a JWT-like token for authenticated user.

        We use a simple JSON + HMAC approach instead of full JWT library
        to avoid additional dependencies. This is sufficient for our use case.

        Args:
            user_email: User's email address

        Returns:
            Token string (base64 encoded JSON with signature)
        """
        import hashlib
        import base64

        payload = {
            "email": user_email,
            "iat": datetime.utcnow().isoformat(),
            "exp": (
                datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
            ).isoformat(),
        }

        # Encode payload
        payload_json = json.dumps(payload, sort_keys=True)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()

        # Create signature
        signature_input = f"{payload_b64}.{JWT_SECRET}"
        signature = hashlib.sha256(signature_input.encode()).hexdigest()

        # Return token: payload.signature
        return f"{payload_b64}.{signature}"

    @staticmethod
    def verify_token(token: str) -> Tuple[bool, Dict]:
        """
        Verify token and return (valid, payload_or_error).

        Args:
            token: Token string to verify

        Returns:
            Tuple of (is_valid, payload_dict or error_dict)
        """
        import hashlib
        import base64

        try:
            if not token or "." not in token:
                return False, {"error": "Invalid token format"}

            parts = token.split(".")
            if len(parts) != 2:
                return False, {"error": "Invalid token format"}

            payload_b64, signature = parts

            # Verify signature
            signature_input = f"{payload_b64}.{JWT_SECRET}"
            expected_signature = hashlib.sha256(signature_input.encode()).hexdigest()

            if signature != expected_signature:
                return False, {"error": "Invalid token signature"}

            # Decode payload
            payload_json = base64.urlsafe_b64decode(payload_b64.encode()).decode()
            payload = json.loads(payload_json)

            # Check expiration
            exp = datetime.fromisoformat(payload["exp"])
            if datetime.utcnow() > exp:
                return False, {"error": "Token expired"}

            return True, payload

        except Exception as e:
            return False, {"error": f"Token verification failed: {str(e)}"}

    @staticmethod
    def require_ext_auth(f):
        """
        Decorator to protect extension endpoints.

        Expects: Authorization: Bearer <token> header
        Injects: request.ext_user_email with authenticated user's email

        Usage:
            @app.route('/ext/protected')
            @ExtensionAuth.require_ext_auth
            def protected_endpoint():
                email = request.ext_user_email
                # ... handle request
        """

        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")

            if not auth_header.startswith("Bearer "):
                return jsonify(
                    {"error": "Missing or invalid authorization header"}
                ), 401

            token = auth_header[7:]  # Remove 'Bearer ' prefix
            valid, payload = ExtensionAuth.verify_token(token)

            if not valid:
                return jsonify({"error": payload.get("error", "Invalid token")}), 401

            # Inject user email into request context
            request.ext_user_email = payload["email"]
            return f(*args, **kwargs)

        return decorated

    @staticmethod
    def invalidate_token(token: str) -> bool:
        """
        Invalidate a token (for logout).

        Note: Since we use stateless tokens, we can't truly invalidate them.
        For now, this is a no-op. In production, you might:
        1. Use a token blacklist in Redis
        2. Shorten token expiry and use refresh tokens
        3. Store token version in user record

        For the extension, the client simply deletes the token on logout.

        Args:
            token: Token to invalidate

        Returns:
            True (always, since client-side deletion is sufficient)
        """
        # Stateless tokens can't be invalidated server-side without a blacklist
        # Client should delete the token from chrome.storage
        return True


# =============================================================================
# ExtensionDB - Database operations for extension tables
# =============================================================================


class ExtensionDB:
    """
    SQLite operations for extension-specific tables.

    Tables managed:
    - ExtensionConversations: Conversation metadata
    - ExtensionMessages: Chat messages
    - ExtensionConversationMemories: Attached PKB claims
    - CustomScripts: Tampermonkey-like scripts (Phase 2)
    - ExtensionWorkflows: Multi-step prompt workflows
    - ExtensionSettings: Per-user settings

    Why separate from main database:
    - Extension conversations don't clutter web UI
    - Simpler schema (no workspaces, no doubts)
    - Can be migrated/backed up independently
    """

    def __init__(self, db_path: str = None):
        """
        Initialize ExtensionDB.

        Args:
            db_path: Path to SQLite database. If None, uses default.
        """
        self.db_path = db_path or get_extension_db_path()
        self.create_tables()

    def _get_conn(self):
        """Get a database connection."""
        return create_connection(self.db_path)

    def create_tables(self):
        """Create extension-specific tables if they don't exist."""
        conn = self._get_conn()
        if conn is None:
            raise RuntimeError(f"Failed to connect to database at {self.db_path}")

        cursor = conn.cursor()

        try:
            # ExtensionConversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExtensionConversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    title TEXT DEFAULT 'New Chat',
                    is_temporary INTEGER DEFAULT 1,
                    model TEXT DEFAULT 'gpt-4',
                    prompt_name TEXT,
                    history_length INTEGER DEFAULT 10,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    summary TEXT,
                    settings_json TEXT
                )
            """)

            # ExtensionMessages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExtensionMessages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    page_context TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) 
                        REFERENCES ExtensionConversations(conversation_id)
                        ON DELETE CASCADE
                )
            """)

            # ExtensionConversationMemories table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExtensionConversationMemories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    attached_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) 
                        REFERENCES ExtensionConversations(conversation_id)
                        ON DELETE CASCADE,
                    UNIQUE(conversation_id, claim_id)
                )
            """)

            # CustomScripts table - Tampermonkey-like user scripts
            # Supports both parsing scripts (extract page content) and functional scripts (multiple actions)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS CustomScripts (
                    script_id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    script_type TEXT DEFAULT 'functional',
                    
                    -- URL Matching
                    match_patterns TEXT NOT NULL,
                    match_type TEXT DEFAULT 'glob',
                    
                    -- Script Code
                    code TEXT NOT NULL,
                    
                    -- Actions (JSON array for functional scripts)
                    actions TEXT,
                    
                    -- Metadata
                    enabled INTEGER DEFAULT 1,
                    version INTEGER DEFAULT 1,
                    conversation_id TEXT,
                    created_with_llm INTEGER DEFAULT 1,
                    
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration: Add new columns if upgrading from old schema
            # This handles existing databases that have the old schema
            try:
                cursor.execute("ALTER TABLE CustomScripts ADD COLUMN description TEXT")
            except:
                pass  # Column already exists
            try:
                cursor.execute(
                    "ALTER TABLE CustomScripts ADD COLUMN script_type TEXT DEFAULT 'functional'"
                )
            except:
                pass
            try:
                cursor.execute(
                    "ALTER TABLE CustomScripts ADD COLUMN match_type TEXT DEFAULT 'glob'"
                )
            except:
                pass
            try:
                cursor.execute("ALTER TABLE CustomScripts ADD COLUMN actions TEXT")
            except:
                pass
            try:
                cursor.execute(
                    "ALTER TABLE CustomScripts ADD COLUMN conversation_id TEXT"
                )
            except:
                pass
            # Rename 'script' to 'code' if old column exists
            try:
                cursor.execute("ALTER TABLE CustomScripts RENAME COLUMN script TO code")
            except:
                pass
            # Remove 'domain' column by recreating table if needed (SQLite limitation)
            # For now, domain column will be ignored if present

            # ExtensionWorkflows table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExtensionWorkflows (
                    workflow_id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ExtensionSettings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ExtensionSettings (
                    user_email TEXT PRIMARY KEY,
                    default_model TEXT DEFAULT 'gpt-4',
                    default_prompt TEXT DEFAULT 'default',
                    history_length INTEGER DEFAULT 10,
                    auto_save INTEGER DEFAULT 0,
                    settings_json TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_conv_user 
                ON ExtensionConversations(user_email)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_conv_updated 
                ON ExtensionConversations(updated_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_msg_conv 
                ON ExtensionMessages(conversation_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_msg_created 
                ON ExtensionMessages(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_mem_conv 
                ON ExtensionConversationMemories(conversation_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_script_user 
                ON CustomScripts(user_email)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_script_enabled 
                ON CustomScripts(user_email, enabled)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_script_type 
                ON CustomScripts(script_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ext_workflow_user
                ON ExtensionWorkflows(user_email)
            """)

            # Schema migrations — add columns that may not exist in older databases
            try:
                cursor.execute(
                    "ALTER TABLE ExtensionMessages ADD COLUMN display_attachments TEXT"
                )
            except Exception:
                pass  # Column already exists

            conn.commit()

        except Error as e:
            raise RuntimeError(f"Failed to create extension tables: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Conversation CRUD
    # -------------------------------------------------------------------------

    def create_conversation(
        self,
        user_email: str,
        title: str = "New Chat",
        is_temporary: bool = True,
        model: str = "gpt-4",
        prompt_name: str = None,
        history_length: int = 10,
    ) -> Dict:
        """
        Create a new extension conversation.

        Args:
            user_email: User's email
            title: Conversation title
            is_temporary: If True, won't be persisted long-term
            model: LLM model to use
            prompt_name: System prompt name
            history_length: Number of messages to include in context

        Returns:
            Dict with conversation details
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        conversation_id = secrets.token_hex(16)
        now = datetime.utcnow().isoformat()

        try:
            cursor.execute(
                """
                INSERT INTO ExtensionConversations 
                (conversation_id, user_email, title, is_temporary, model, 
                 prompt_name, history_length, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    conversation_id,
                    user_email,
                    title,
                    1 if is_temporary else 0,
                    model,
                    prompt_name,
                    history_length,
                    now,
                    now,
                ),
            )
            conn.commit()

            return {
                "conversation_id": conversation_id,
                "user_email": user_email,
                "title": title,
                "is_temporary": is_temporary,
                "model": model,
                "prompt_name": prompt_name,
                "history_length": history_length,
                "created_at": now,
                "updated_at": now,
                "messages": [],
                "attached_memory_ids": [],
            }

        except Error as e:
            raise RuntimeError(f"Failed to create conversation: {e}")
        finally:
            conn.close()

    def get_conversation(self, conversation_id: str, user_email: str) -> Optional[Dict]:
        """
        Get a conversation by ID for a specific user.

        Args:
            conversation_id: Conversation ID
            user_email: User's email (for authorization)

        Returns:
            Conversation dict or None if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # Get conversation metadata
            cursor.execute(
                """
                SELECT conversation_id, user_email, title, is_temporary,
                       model, prompt_name, history_length, created_at,
                       updated_at, summary, settings_json
                FROM ExtensionConversations
                WHERE conversation_id = ? AND user_email = ?
            """,
                (conversation_id, user_email),
            )

            row = cursor.fetchone()
            if not row:
                return None

            conv = {
                "conversation_id": row[0],
                "user_email": row[1],
                "title": row[2],
                "is_temporary": bool(row[3]),
                "model": row[4],
                "prompt_name": row[5],
                "history_length": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "summary": row[9],
                "settings": json.loads(row[10]) if row[10] else {},
            }

            # Get messages
            cursor.execute(
                """
                SELECT message_id, role, content, page_context, display_attachments, created_at
                FROM ExtensionMessages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
            """,
                (conversation_id,),
            )

            conv["messages"] = [
                {
                    "message_id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "page_context": json.loads(r[3]) if r[3] else None,
                    "display_attachments": json.loads(r[4]) if r[4] else None,
                    "created_at": r[5],
                }
                for r in cursor.fetchall()
            ]

            # Get attached memories
            cursor.execute(
                """
                SELECT claim_id FROM ExtensionConversationMemories
                WHERE conversation_id = ?
            """,
                (conversation_id,),
            )

            conv["attached_memory_ids"] = [r[0] for r in cursor.fetchall()]

            return conv

        except Error as e:
            raise RuntimeError(f"Failed to get conversation: {e}")
        finally:
            conn.close()

    def list_conversations(
        self,
        user_email: str,
        limit: int = 50,
        offset: int = 0,
        include_temporary: bool = True,
    ) -> List[Dict]:
        """
        List conversations for a user.

        Args:
            user_email: User's email
            limit: Maximum number to return
            offset: Offset for pagination
            include_temporary: Whether to include temporary conversations

        Returns:
            List of conversation summaries (without messages)
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            if include_temporary:
                cursor.execute(
                    """
                    SELECT conversation_id, title, is_temporary, model,
                           created_at, updated_at, 
                           (SELECT COUNT(*) FROM ExtensionMessages 
                            WHERE ExtensionMessages.conversation_id = 
                                  ExtensionConversations.conversation_id) as msg_count
                    FROM ExtensionConversations
                    WHERE user_email = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """,
                    (user_email, limit, offset),
                )
            else:
                cursor.execute(
                    """
                    SELECT conversation_id, title, is_temporary, model,
                           created_at, updated_at,
                           (SELECT COUNT(*) FROM ExtensionMessages 
                            WHERE ExtensionMessages.conversation_id = 
                                  ExtensionConversations.conversation_id) as msg_count
                    FROM ExtensionConversations
                    WHERE user_email = ? AND is_temporary = 0
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """,
                    (user_email, limit, offset),
                )

            return [
                {
                    "conversation_id": r[0],
                    "title": r[1],
                    "is_temporary": bool(r[2]),
                    "model": r[3],
                    "created_at": r[4],
                    "updated_at": r[5],
                    "message_count": r[6],
                }
                for r in cursor.fetchall()
            ]

        except Error as e:
            raise RuntimeError(f"Failed to list conversations: {e}")
        finally:
            conn.close()

    def count_conversations(self, user_email: str) -> int:
        """Count total conversations for a user."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT COUNT(*) FROM ExtensionConversations
                WHERE user_email = ?
            """,
                (user_email,),
            )
            return cursor.fetchone()[0]
        except Error as e:
            raise RuntimeError(f"Failed to count conversations: {e}")
        finally:
            conn.close()

    def update_conversation(
        self, conversation_id: str, user_email: str, **updates
    ) -> bool:
        """
        Update conversation metadata.

        Args:
            conversation_id: Conversation ID
            user_email: User's email (for authorization)
            **updates: Fields to update (title, is_temporary, model, etc.)

        Returns:
            True if updated, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        allowed_fields = {
            "title",
            "is_temporary",
            "model",
            "prompt_name",
            "history_length",
            "summary",
            "settings_json",
        }

        # Filter to allowed fields only
        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not valid_updates:
            return False

        # Convert is_temporary to int if present
        if "is_temporary" in valid_updates:
            valid_updates["is_temporary"] = 1 if valid_updates["is_temporary"] else 0

        # Build update query
        set_clause = ", ".join([f"{k} = ?" for k in valid_updates.keys()])
        values = list(valid_updates.values())
        values.extend([datetime.utcnow().isoformat(), conversation_id, user_email])

        try:
            cursor.execute(
                f"""
                UPDATE ExtensionConversations
                SET {set_clause}, updated_at = ?
                WHERE conversation_id = ? AND user_email = ?
            """,
                values,
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to update conversation: {e}")
        finally:
            conn.close()

    def delete_conversation(self, conversation_id: str, user_email: str) -> bool:
        """
        Delete a conversation and all its messages.

        Args:
            conversation_id: Conversation ID
            user_email: User's email (for authorization)

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # Delete messages first (due to foreign key)
            cursor.execute(
                """
                DELETE FROM ExtensionMessages
                WHERE conversation_id = ? AND conversation_id IN (
                    SELECT conversation_id FROM ExtensionConversations
                    WHERE user_email = ?
                )
            """,
                (conversation_id, user_email),
            )

            # Delete attached memories
            cursor.execute(
                """
                DELETE FROM ExtensionConversationMemories
                WHERE conversation_id = ?
            """,
                (conversation_id,),
            )

            # Delete conversation
            cursor.execute(
                """
                DELETE FROM ExtensionConversations
                WHERE conversation_id = ? AND user_email = ?
            """,
                (conversation_id, user_email),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to delete conversation: {e}")

    def delete_temporary_conversations(self, user_email: str) -> int:
        """
        Delete all temporary (unsaved) conversations for a user.
        Called when creating a new conversation to clean up old temporary ones.

        Args:
            user_email: User's email

        Returns:
            Number of conversations deleted
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # First get IDs of temporary conversations to delete their messages
            cursor.execute(
                """
                SELECT conversation_id FROM ExtensionConversations
                WHERE user_email = ? AND is_temporary = 1
            """,
                (user_email,),
            )

            temp_conv_ids = [row[0] for row in cursor.fetchall()]

            if not temp_conv_ids:
                return 0

            # Delete messages for these conversations
            placeholders = ",".join("?" * len(temp_conv_ids))
            cursor.execute(
                f"""
                DELETE FROM ExtensionMessages
                WHERE conversation_id IN ({placeholders})
            """,
                temp_conv_ids,
            )

            # Delete attached memories
            cursor.execute(
                f"""
                DELETE FROM ExtensionConversationMemories
                WHERE conversation_id IN ({placeholders})
            """,
                temp_conv_ids,
            )

            # Delete the conversations
            cursor.execute(
                """
                DELETE FROM ExtensionConversations
                WHERE user_email = ? AND is_temporary = 1
            """,
                (user_email,),
            )

            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count

        except Error as e:
            raise RuntimeError(f"Failed to delete temporary conversations: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Message operations
    # -------------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        page_context: Dict = None,
        display_attachments: list = None,
    ) -> Dict:
        """
        Add a message to a conversation.

        Args:
            conversation_id: Conversation ID
            role: 'user' or 'assistant'
            content: Message content
            page_context: Optional dict with url, title, content_snippet
            display_attachments: Optional list of attachment metadata for UI display
                (not sent to LLM). Each item: {type, name, thumbnail}.

        Returns:
            Created message dict
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        message_id = secrets.token_hex(8)
        now = datetime.utcnow().isoformat()
        page_context_json = json.dumps(page_context) if page_context else None
        display_attachments_json = (
            json.dumps(display_attachments) if display_attachments else None
        )

        try:
            cursor.execute(
                """
                INSERT INTO ExtensionMessages
                (message_id, conversation_id, role, content, page_context, display_attachments, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    page_context_json,
                    display_attachments_json,
                    now,
                ),
            )

            # Update conversation's updated_at
            cursor.execute(
                """
                UPDATE ExtensionConversations
                SET updated_at = ?
                WHERE conversation_id = ?
            """,
                (now, conversation_id),
            )

            conn.commit()

            return {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "page_context": page_context,
                "display_attachments": display_attachments,
                "created_at": now,
            }

        except Error as e:
            raise RuntimeError(f"Failed to add message: {e}")
        finally:
            conn.close()

    def get_messages(self, conversation_id: str, limit: int = None) -> List[Dict]:
        """
        Get messages for a conversation.

        Args:
            conversation_id: Conversation ID
            limit: If set, get last N messages only

        Returns:
            List of message dicts
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            if limit:
                # Get last N messages
                cursor.execute(
                    """
                    SELECT message_id, role, content, page_context, display_attachments, created_at
                    FROM ExtensionMessages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (conversation_id, limit),
                )
                messages = list(reversed(cursor.fetchall()))
            else:
                cursor.execute(
                    """
                    SELECT message_id, role, content, page_context, display_attachments, created_at
                    FROM ExtensionMessages
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC
                """,
                    (conversation_id,),
                )
                messages = cursor.fetchall()

            return [
                {
                    "message_id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "page_context": json.loads(r[3]) if r[3] else None,
                    "display_attachments": json.loads(r[4]) if r[4] else None,
                    "created_at": r[5],
                }
                for r in messages
            ]

        except Error as e:
            raise RuntimeError(f"Failed to get messages: {e}")
        finally:
            conn.close()

    def delete_message(
        self, conversation_id: str, message_id: str, user_email: str
    ) -> bool:
        """
        Delete a specific message.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID to delete
            user_email: User's email (for authorization)

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # Verify ownership before deleting
            cursor.execute(
                """
                DELETE FROM ExtensionMessages
                WHERE message_id = ? 
                  AND conversation_id = ?
                  AND conversation_id IN (
                      SELECT conversation_id FROM ExtensionConversations
                      WHERE user_email = ?
                  )
            """,
                (message_id, conversation_id, user_email),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to delete message: {e}")
        finally:
            conn.close()

    def update_message(
        self, conversation_id: str, message_id: str, user_email: str, content: str
    ) -> bool:
        """
        Update a message's content.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID to update
            user_email: User's email (for authorization)
            content: New message content

        Returns:
            True if updated, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE ExtensionMessages
                SET content = ?
                WHERE message_id = ?
                  AND conversation_id = ?
                  AND conversation_id IN (
                      SELECT conversation_id FROM ExtensionConversations
                      WHERE user_email = ?
                  )
            """,
                (content, message_id, conversation_id, user_email),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to update message: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Memory attachment
    # -------------------------------------------------------------------------

    def attach_memory(self, conversation_id: str, claim_id: str) -> bool:
        """Attach a PKB claim to a conversation."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO ExtensionConversationMemories
                (conversation_id, claim_id)
                VALUES (?, ?)
            """,
                (conversation_id, claim_id),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to attach memory: {e}")
        finally:
            conn.close()

    def detach_memory(self, conversation_id: str, claim_id: str) -> bool:
        """Detach a PKB claim from a conversation."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                DELETE FROM ExtensionConversationMemories
                WHERE conversation_id = ? AND claim_id = ?
            """,
                (conversation_id, claim_id),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to detach memory: {e}")
        finally:
            conn.close()

    def get_attached_memories(self, conversation_id: str) -> List[str]:
        """Get list of claim IDs attached to a conversation."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT claim_id FROM ExtensionConversationMemories
                WHERE conversation_id = ?
            """,
                (conversation_id,),
            )

            return [r[0] for r in cursor.fetchall()]

        except Error as e:
            raise RuntimeError(f"Failed to get attached memories: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    def get_settings(self, user_email: str) -> Dict:
        """Get user's extension settings."""
        conn = self._get_conn()
        cursor = conn.cursor()

        defaults = {
            "default_model": "gpt-4",
            "default_prompt": "default",
            "history_length": 10,
            "auto_save": False,
        }

        try:
            cursor.execute(
                """
                SELECT default_model, default_prompt, history_length, 
                       auto_save, settings_json
                FROM ExtensionSettings
                WHERE user_email = ?
            """,
                (user_email,),
            )

            row = cursor.fetchone()
            if not row:
                return defaults

            settings = {
                "default_model": row[0] or defaults["default_model"],
                "default_prompt": row[1] or defaults["default_prompt"],
                "history_length": row[2] or defaults["history_length"],
                "auto_save": bool(row[3]),
            }

            # Merge additional settings from JSON
            if row[4]:
                extra = json.loads(row[4])
                settings.update(extra)

            return settings

        except Error as e:
            raise RuntimeError(f"Failed to get settings: {e}")
        finally:
            conn.close()

    def update_settings(self, user_email: str, **updates) -> bool:
        """Update user's extension settings."""
        conn = self._get_conn()
        cursor = conn.cursor()

        core_fields = {"default_model", "default_prompt", "history_length", "auto_save"}
        core_updates = {k: v for k, v in updates.items() if k in core_fields}
        extra_updates = {k: v for k, v in updates.items() if k not in core_fields}

        try:
            # Check if settings exist
            cursor.execute(
                """
                SELECT 1 FROM ExtensionSettings WHERE user_email = ?
            """,
                (user_email,),
            )

            now = datetime.utcnow().isoformat()

            if cursor.fetchone():
                # Update existing
                if core_updates:
                    # Convert auto_save to int
                    if "auto_save" in core_updates:
                        core_updates["auto_save"] = (
                            1 if core_updates["auto_save"] else 0
                        )

                    set_clause = ", ".join([f"{k} = ?" for k in core_updates.keys()])
                    values = list(core_updates.values())
                    values.extend([now, user_email])

                    cursor.execute(
                        f"""
                        UPDATE ExtensionSettings
                        SET {set_clause}, updated_at = ?
                        WHERE user_email = ?
                    """,
                        values,
                    )

                if extra_updates:
                    # Get existing extra settings and merge
                    cursor.execute(
                        """
                        SELECT settings_json FROM ExtensionSettings
                        WHERE user_email = ?
                    """,
                        (user_email,),
                    )
                    row = cursor.fetchone()
                    existing = json.loads(row[0]) if row and row[0] else {}
                    existing.update(extra_updates)

                    cursor.execute(
                        """
                        UPDATE ExtensionSettings
                        SET settings_json = ?, updated_at = ?
                        WHERE user_email = ?
                    """,
                        (json.dumps(existing), now, user_email),
                    )
            else:
                # Insert new
                auto_save = 1 if core_updates.get("auto_save", False) else 0
                cursor.execute(
                    """
                    INSERT INTO ExtensionSettings
                    (user_email, default_model, default_prompt, history_length,
                     auto_save, settings_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        user_email,
                        core_updates.get("default_model", "gpt-4"),
                        core_updates.get("default_prompt", "default"),
                        core_updates.get("history_length", 10),
                        auto_save,
                        json.dumps(extra_updates) if extra_updates else None,
                        now,
                    ),
                )

            conn.commit()
            return True

        except Error as e:
            raise RuntimeError(f"Failed to update settings: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Custom Scripts CRUD
    # -------------------------------------------------------------------------

    def create_custom_script(
        self,
        user_email: str,
        name: str,
        match_patterns: List[str],
        code: str,
        description: str = None,
        script_type: str = "functional",
        match_type: str = "glob",
        actions: List[Dict] = None,
        conversation_id: str = None,
        created_with_llm: bool = True,
    ) -> Dict:
        """
        Create a new custom script.

        Args:
            user_email: User's email
            name: Script name
            match_patterns: List of URL patterns (glob or regex)
            code: JavaScript code
            description: Optional description
            script_type: 'functional' or 'parsing'
            match_type: 'glob' or 'regex'
            actions: List of action definitions (for functional scripts)
            conversation_id: Optional link to creation conversation
            created_with_llm: Whether script was created via LLM

        Returns:
            Created script dict
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        script_id = secrets.token_hex(16)
        now = datetime.utcnow().isoformat()

        try:
            cursor.execute(
                """
                INSERT INTO CustomScripts
                (script_id, user_email, name, description, script_type,
                 match_patterns, match_type, code, actions, enabled,
                 version, conversation_id, created_with_llm, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    script_id,
                    user_email,
                    name,
                    description,
                    script_type,
                    json.dumps(match_patterns),
                    match_type,
                    code,
                    json.dumps(actions) if actions else None,
                    1,  # enabled
                    1,  # version
                    conversation_id,
                    1 if created_with_llm else 0,
                    now,
                    now,
                ),
            )

            conn.commit()

            return {
                "script_id": script_id,
                "user_email": user_email,
                "name": name,
                "description": description,
                "script_type": script_type,
                "match_patterns": match_patterns,
                "match_type": match_type,
                "code": code,
                "actions": actions or [],
                "enabled": True,
                "version": 1,
                "conversation_id": conversation_id,
                "created_with_llm": created_with_llm,
                "created_at": now,
                "updated_at": now,
            }

        except Error as e:
            raise RuntimeError(f"Failed to create script: {e}")
        finally:
            conn.close()

    def get_custom_script(self, user_email: str, script_id: str) -> Optional[Dict]:
        """
        Get a specific script by ID.

        Args:
            user_email: User's email (for authorization)
            script_id: Script ID

        Returns:
            Script dict or None if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT script_id, user_email, name, description, script_type,
                       match_patterns, match_type, code, actions, enabled,
                       version, conversation_id, created_with_llm,
                       created_at, updated_at
                FROM CustomScripts
                WHERE script_id = ? AND user_email = ?
            """,
                (script_id, user_email),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return {
                "script_id": row[0],
                "user_email": row[1],
                "name": row[2],
                "description": row[3],
                "script_type": row[4],
                "match_patterns": json.loads(row[5]) if row[5] else [],
                "match_type": row[6],
                "code": row[7],
                "actions": json.loads(row[8]) if row[8] else [],
                "enabled": bool(row[9]),
                "version": row[10],
                "conversation_id": row[11],
                "created_with_llm": bool(row[12]),
                "created_at": row[13],
                "updated_at": row[14],
            }

        except Error as e:
            raise RuntimeError(f"Failed to get script: {e}")
        finally:
            conn.close()

    def get_custom_scripts(
        self,
        user_email: str,
        enabled_only: bool = False,
        script_type: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """
        List user's custom scripts.

        Args:
            user_email: User's email
            enabled_only: If True, only return enabled scripts
            script_type: Optional filter by type ('functional' or 'parsing')
            limit: Maximum number to return
            offset: Pagination offset

        Returns:
            List of script dicts
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            query = """
                SELECT script_id, user_email, name, description, script_type,
                       match_patterns, match_type, code, actions, enabled,
                       version, conversation_id, created_with_llm,
                       created_at, updated_at
                FROM CustomScripts
                WHERE user_email = ?
            """
            params = [user_email]

            if enabled_only:
                query += " AND enabled = 1"

            if script_type:
                query += " AND script_type = ?"
                params.append(script_type)

            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            return [
                {
                    "script_id": row[0],
                    "user_email": row[1],
                    "name": row[2],
                    "description": row[3],
                    "script_type": row[4],
                    "match_patterns": json.loads(row[5]) if row[5] else [],
                    "match_type": row[6],
                    "code": row[7],
                    "actions": json.loads(row[8]) if row[8] else [],
                    "enabled": bool(row[9]),
                    "version": row[10],
                    "conversation_id": row[11],
                    "created_with_llm": bool(row[12]),
                    "created_at": row[13],
                    "updated_at": row[14],
                }
                for row in cursor.fetchall()
            ]

        except Error as e:
            raise RuntimeError(f"Failed to list scripts: {e}")
        finally:
            conn.close()

    def update_custom_script(self, user_email: str, script_id: str, **updates) -> bool:
        """
        Update a custom script.

        Args:
            user_email: User's email (for authorization)
            script_id: Script ID
            **updates: Fields to update (name, description, code, actions, etc.)

        Returns:
            True if updated, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        allowed_fields = {
            "name",
            "description",
            "script_type",
            "match_patterns",
            "match_type",
            "code",
            "actions",
            "enabled",
            "conversation_id",
        }

        # Filter to allowed fields
        valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not valid_updates:
            return False

        # Convert complex types to JSON
        if "match_patterns" in valid_updates:
            valid_updates["match_patterns"] = json.dumps(
                valid_updates["match_patterns"]
            )
        if "actions" in valid_updates:
            valid_updates["actions"] = json.dumps(valid_updates["actions"])
        if "enabled" in valid_updates:
            valid_updates["enabled"] = 1 if valid_updates["enabled"] else 0

        try:
            # Build update query
            set_clause = ", ".join([f"{k} = ?" for k in valid_updates.keys()])
            values = list(valid_updates.values())

            now = datetime.utcnow().isoformat()
            values.extend([now, script_id, user_email])

            cursor.execute(
                f"""
                UPDATE CustomScripts
                SET {set_clause}, version = version + 1, updated_at = ?
                WHERE script_id = ? AND user_email = ?
            """,
                values,
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to update script: {e}")
        finally:
            conn.close()

    def delete_custom_script(self, user_email: str, script_id: str) -> bool:
        """
        Delete a custom script.

        Args:
            user_email: User's email (for authorization)
            script_id: Script ID

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                DELETE FROM CustomScripts
                WHERE script_id = ? AND user_email = ?
            """,
                (script_id, user_email),
            )

            conn.commit()
            return cursor.rowcount > 0

        except Error as e:
            raise RuntimeError(f"Failed to delete script: {e}")
        finally:
            conn.close()

    def get_scripts_for_url(self, user_email: str, url: str) -> List[Dict]:
        """
        Get all enabled scripts that match a given URL.

        Supports glob patterns (with * wildcards) and regex patterns.

        Args:
            user_email: User's email
            url: Full URL to match against

        Returns:
            List of matching script dicts
        """
        import fnmatch
        import re

        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            # Get all enabled scripts for user
            cursor.execute(
                """
                SELECT script_id, user_email, name, description, script_type,
                       match_patterns, match_type, code, actions, enabled,
                       version, conversation_id, created_with_llm,
                       created_at, updated_at
                FROM CustomScripts
                WHERE user_email = ? AND enabled = 1
            """,
                (user_email,),
            )

            matching_scripts = []

            for row in cursor.fetchall():
                match_patterns = json.loads(row[5]) if row[5] else []
                match_type = row[6] or "glob"

                # Check if URL matches any pattern
                matches = False
                for pattern in match_patterns:
                    try:
                        if match_type == "regex":
                            if re.match(pattern, url):
                                matches = True
                                break
                        else:  # glob
                            # Convert glob to regex for proper URL matching
                            # Handle *:// prefix for any protocol
                            regex_pattern = pattern.replace(".", r"\.")
                            regex_pattern = regex_pattern.replace("*", ".*")
                            regex_pattern = f"^{regex_pattern}$"
                            if re.match(regex_pattern, url):
                                matches = True
                                break
                    except re.error:
                        continue  # Skip invalid patterns

                if matches:
                    matching_scripts.append(
                        {
                            "script_id": row[0],
                            "user_email": row[1],
                            "name": row[2],
                            "description": row[3],
                            "script_type": row[4],
                            "match_patterns": match_patterns,
                            "match_type": match_type,
                            "code": row[7],
                            "actions": json.loads(row[8]) if row[8] else [],
                            "enabled": bool(row[9]),
                            "version": row[10],
                            "conversation_id": row[11],
                            "created_with_llm": bool(row[12]),
                            "created_at": row[13],
                            "updated_at": row[14],
                        }
                    )

            return matching_scripts

        except Error as e:
            raise RuntimeError(f"Failed to get scripts for URL: {e}")
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Workflow CRUD
    # -------------------------------------------------------------------------

    def create_workflow(self, user_email: str, name: str, steps: List[Dict]) -> Dict:
        """
        Create a new multi-step prompt workflow.

        Args:
            user_email: User's email.
            name: Workflow name.
            steps: List of step dicts with {title, prompt}.

        Returns:
            Created workflow dict.
        """
        conn = self._get_conn()
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
            raise RuntimeError(f"Failed to create workflow: {e}")
        finally:
            conn.close()

    def get_workflow(self, user_email: str, workflow_id: str) -> Optional[Dict]:
        """
        Get a workflow by ID.

        Args:
            user_email: User's email.
            workflow_id: Workflow ID.

        Returns:
            Workflow dict or None.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT workflow_id, user_email, name, steps_json, created_at, updated_at
                FROM ExtensionWorkflows
                WHERE workflow_id = ? AND user_email = ?
            """,
                (workflow_id, user_email),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "workflow_id": row[0],
                "user_email": row[1],
                "name": row[2],
                "steps": json.loads(row[3]) if row[3] else [],
                "created_at": row[4],
                "updated_at": row[5],
            }
        except Error as e:
            raise RuntimeError(f"Failed to get workflow: {e}")
        finally:
            conn.close()

    def list_workflows(self, user_email: str) -> List[Dict]:
        """
        List workflows for a user.

        Args:
            user_email: User's email.

        Returns:
            List of workflow dicts.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT workflow_id, user_email, name, steps_json, created_at, updated_at
                FROM ExtensionWorkflows
                WHERE user_email = ?
                ORDER BY updated_at DESC
            """,
                (user_email,),
            )
            rows = cursor.fetchall()
            workflows = []
            for row in rows:
                workflows.append(
                    {
                        "workflow_id": row[0],
                        "user_email": row[1],
                        "name": row[2],
                        "steps": json.loads(row[3]) if row[3] else [],
                        "created_at": row[4],
                        "updated_at": row[5],
                    }
                )
            return workflows
        except Error as e:
            raise RuntimeError(f"Failed to list workflows: {e}")
        finally:
            conn.close()

    def update_workflow(
        self, user_email: str, workflow_id: str, name: str, steps: List[Dict]
    ) -> bool:
        """
        Update an existing workflow.

        Args:
            user_email: User's email.
            workflow_id: Workflow ID.
            name: Updated name.
            steps: Updated steps list.

        Returns:
            True if updated, False otherwise.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        try:
            cursor.execute(
                """
                UPDATE ExtensionWorkflows
                SET name = ?, steps_json = ?, updated_at = ?
                WHERE workflow_id = ? AND user_email = ?
            """,
                (name, json.dumps(steps), now, workflow_id, user_email),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            raise RuntimeError(f"Failed to update workflow: {e}")
        finally:
            conn.close()

    def delete_workflow(self, user_email: str, workflow_id: str) -> bool:
        """
        Delete a workflow.

        Args:
            user_email: User's email.
            workflow_id: Workflow ID.

        Returns:
            True if deleted, False otherwise.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                DELETE FROM ExtensionWorkflows
                WHERE workflow_id = ? AND user_email = ?
            """,
                (workflow_id, user_email),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            raise RuntimeError(f"Failed to delete workflow: {e}")
        finally:
            conn.close()


# =============================================================================
# ExtensionConversation - Simplified conversation class
# =============================================================================


class ExtensionConversation:
    """
    Simplified conversation for extension use.

    Key differences from main Conversation class:
    1. No workspaces (extension uses flat list)
    2. Temporary by default (web UI saves by default)
    3. Page context storage (URL, title, content snippet)
    4. Simpler memory model (no running_summary complexity for now)

    Reuses from existing codebase:
    - LLM call logic via CallLLm
    - PKB context retrieval via _get_pkb_context pattern
    - Message formatting patterns
    """

    def __init__(
        self,
        conversation_id: str,
        user_email: str,
        db: ExtensionDB,
        title: str = None,
        is_temporary: bool = True,
        model: str = "gpt-4",
        prompt_name: str = None,
        history_length: int = 10,
    ):
        self.conversation_id = conversation_id
        self.user_email = user_email
        self.db = db
        self.title = title or "New Chat"
        self.is_temporary = is_temporary
        self.model = model
        self.prompt_name = prompt_name
        self.history_length = history_length
        self.messages = []
        self.attached_memory_ids = []
        self.summary = None

    @classmethod
    def load(
        cls, conversation_id: str, user_email: str, db: ExtensionDB
    ) -> Optional["ExtensionConversation"]:
        """Load an existing conversation from database."""
        data = db.get_conversation(conversation_id, user_email)
        if not data:
            return None

        conv = cls(
            conversation_id=data["conversation_id"],
            user_email=data["user_email"],
            db=db,
            title=data["title"],
            is_temporary=data["is_temporary"],
            model=data["model"],
            prompt_name=data["prompt_name"],
            history_length=data["history_length"],
        )
        conv.messages = data["messages"]
        conv.attached_memory_ids = data["attached_memory_ids"]
        conv.summary = data.get("summary")

        return conv

    @classmethod
    def create(
        cls, user_email: str, db: ExtensionDB, **kwargs
    ) -> "ExtensionConversation":
        """Create a new conversation."""
        data = db.create_conversation(user_email, **kwargs)

        return cls(
            conversation_id=data["conversation_id"],
            user_email=user_email,
            db=db,
            title=data["title"],
            is_temporary=data["is_temporary"],
            model=data["model"],
            prompt_name=data["prompt_name"],
            history_length=data["history_length"],
        )

    def add_message(
        self,
        role: str,
        content: str,
        page_context: Dict = None,
        display_attachments: list = None,
    ) -> Dict:
        """Add a message to the conversation."""
        import logging

        logger = logging.getLogger(__name__)

        msg = self.db.add_message(
            self.conversation_id,
            role,
            content,
            page_context,
            display_attachments=display_attachments,
        )
        self.messages.append(msg)
        logger.info(
            f"[DEBUG] add_message: Added {role} message to conversation {self.conversation_id}, content_length={len(content)}, message_id={msg.get('message_id')}"
        )
        return msg

    def get_history_for_llm(self, limit: int = None) -> List[Dict]:
        """
        Get message history formatted for LLM call.

        System messages (e.g. uploaded document text) are always included
        regardless of the history window, since they contain reference
        material the LLM needs for answering.

        Args:
            limit: Override history_length if provided

        Returns:
            List of message dicts for LLM API
        """
        import logging

        logger = logging.getLogger(__name__)

        n = limit or self.history_length
        logger.info(
            f"[DEBUG] get_history_for_llm: Total messages={len(self.messages)}, history_length={n}"
        )

        # Always include system messages (uploaded docs, etc.) regardless of window
        system_msgs = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.messages
            if msg["role"] == "system"
        ]
        logger.info(
            f"[DEBUG] get_history_for_llm: Found {len(system_msgs)} system messages"
        )
        non_system_msgs = [msg for msg in self.messages if msg["role"] != "system"]
        recent_messages = non_system_msgs[-n:] if n else non_system_msgs
        logger.info(
            f"[DEBUG] get_history_for_llm: Selected {len(recent_messages)} recent non-system messages (out of {len(non_system_msgs)})"
        )

        result = system_msgs + [
            {"role": msg["role"], "content": msg["content"]} for msg in recent_messages
        ]
        logger.info(
            f"[DEBUG] get_history_for_llm: Returning {len(result)} total messages, roles={[m['role'] for m in result]}"
        )
        return result

    def get_pkb_context(self, query: str, keys: Dict) -> str:
        """
        Retrieve relevant PKB memories.

        This leverages the existing PKB infrastructure.

        Args:
            query: Current user query
            keys: API keys dict

        Returns:
            Formatted context string from relevant memories
        """
        # Import here to avoid circular dependency
        try:
            from Conversation import Conversation

            # Create a minimal Conversation instance to access PKB method
            # This is a bit hacky but avoids duplicating PKB retrieval logic
            temp_conv = object.__new__(Conversation)
            temp_conv._storage = "/tmp"  # Not used for PKB

            context = temp_conv._get_pkb_context(
                user_email=self.user_email,
                query=query,
                conversation_summary=self.summary or "",
                k=10,
                attached_claim_ids=self.attached_memory_ids,
            )

            return context if context else ""

        except Exception as e:
            # If PKB fails, continue without it
            import logging

            logging.getLogger(__name__).warning(f"PKB context retrieval failed: {e}")
            return ""

    def update_title(self, title: str):
        """Update conversation title."""
        self.title = title
        self.db.update_conversation(self.conversation_id, self.user_email, title=title)

    def save_permanently(self):
        """Convert temporary conversation to permanent."""
        self.is_temporary = False
        self.db.update_conversation(
            self.conversation_id, self.user_email, is_temporary=False
        )

    def delete(self):
        """Delete this conversation."""
        self.db.delete_conversation(self.conversation_id, self.user_email)

    def to_dict(self) -> Dict:
        """Convert conversation to dict representation."""
        return {
            "conversation_id": self.conversation_id,
            "user_email": self.user_email,
            "title": self.title,
            "is_temporary": self.is_temporary,
            "model": self.model,
            "prompt_name": self.prompt_name,
            "history_length": self.history_length,
            "messages": self.messages,
            "attached_memory_ids": self.attached_memory_ids,
            "summary": self.summary,
        }


# =============================================================================
# Helper functions
# =============================================================================


def keyParser_for_extension() -> Dict:
    """
    Get API keys for extension use.

    This is similar to keyParser in server.py but doesn't need session
    since extension uses token auth. Keys are always from environment.

    Returns:
        Dict of API keys
    """
    import os
    import ast

    keyStore = {
        "openAIKey": os.getenv("openAIKey", ""),
        "jinaAIKey": os.getenv("jinaAIKey", ""),
        "elevenLabsKey": os.getenv("elevenLabsKey", ""),
        "ASSEMBLYAI_API_KEY": os.getenv("ASSEMBLYAI_API_KEY", ""),
        "mathpixId": os.getenv("mathpixId", ""),
        "mathpixKey": os.getenv("mathpixKey", ""),
        "cohereKey": os.getenv("cohereKey", ""),
        "ai21Key": os.getenv("ai21Key", ""),
        "bingKey": os.getenv("bingKey", ""),
        "serpApiKey": os.getenv("serpApiKey", ""),
        "googleSearchApiKey": os.getenv("googleSearchApiKey", ""),
        "googleSearchCxId": os.getenv("googleSearchCxId", ""),
        "openai_models_list": os.getenv("openai_models_list", "[]"),
        "scrapingBrowserUrl": os.getenv("scrapingBrowserUrl", ""),
        "vllmUrl": os.getenv("vllmUrl", ""),
        "vllmLargeModelUrl": os.getenv("vllmLargeModelUrl", ""),
        "vllmSmallModelUrl": os.getenv("vllmSmallModelUrl", ""),
        "tgiUrl": os.getenv("tgiUrl", ""),
        "tgiLargeModelUrl": os.getenv("tgiLargeModelUrl", ""),
        "tgiSmallModelUrl": os.getenv("tgiSmallModelUrl", ""),
        "embeddingsUrl": os.getenv("embeddingsUrl", ""),
        "zenrows": os.getenv("zenrows", ""),
        "scrapingant": os.getenv("scrapingant", ""),
        "brightdataUrl": os.getenv("brightdataUrl", ""),
        "brightdataProxy": os.getenv("brightdataProxy", ""),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
    }

    # Parse openai_models_list if vllm URLs are set
    if (
        keyStore["vllmUrl"].strip() != ""
        or keyStore["vllmLargeModelUrl"].strip() != ""
        or keyStore["vllmSmallModelUrl"].strip() != ""
    ):
        try:
            keyStore["openai_models_list"] = ast.literal_eval(
                keyStore["openai_models_list"]
            )
        except:
            keyStore["openai_models_list"] = []

    # Clean up empty values
    for k, v in list(keyStore.items()):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            keyStore[k] = None

    return keyStore


# =============================================================================
# Module initialization
# =============================================================================

# Global ExtensionDB instance (will be initialized when paths are set)
_extension_db = None


def get_extension_db() -> ExtensionDB:
    """Get or initialize the global ExtensionDB instance."""
    global _extension_db
    if _extension_db is None:
        _extension_db = ExtensionDB()
    return _extension_db
