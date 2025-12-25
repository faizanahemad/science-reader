"""
Extension Server - Standalone Flask server for Chrome Extension

This is a separate server from server.py that provides APIs specifically
for the Chrome extension. It shares the same user database, prompts, and
memories with the main application but has its own conversation storage.

Key features:
- JWT-based token authentication (no sessions)
- Read-only access to prompts (from prompts.json via prompt_lib)
- Read-only access to memories (from truth_management_system/PKB)
- LLM calls via code_common/call_llm.py
- Separate SQLite storage for extension conversations

Usage:
    conda activate science-reader
    python extension_server.py [--port 5001] [--debug]

API Endpoints:
    POST /ext/auth/login          - Login and get JWT token
    POST /ext/auth/logout         - Logout (client-side token deletion)
    POST /ext/auth/verify         - Verify token validity
    
    GET  /ext/prompts             - List available prompts
    GET  /ext/prompts/<name>      - Get specific prompt content
    
    GET  /ext/memories            - List user's memories (PKB claims)
    POST /ext/memories/search     - Search memories
    GET  /ext/memories/<id>       - Get specific memory
    
    GET  /ext/conversations       - List conversations
    POST /ext/conversations       - Create new conversation
    GET  /ext/conversations/<id>  - Get conversation details
    PUT  /ext/conversations/<id>  - Update conversation
    DELETE /ext/conversations/<id> - Delete conversation
    
    POST /ext/chat/<id>           - Send message and get response (streaming)
    POST /ext/chat/<id>/message   - Add message without LLM response
    
    GET  /ext/settings            - Get user settings
    PUT  /ext/settings            - Update user settings
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from queue import Queue
from functools import wraps

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# =============================================================================
# Logging Setup
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Flask App Setup
# =============================================================================

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "extension-server-secret-key")

# Enable CORS for Chrome extension
CORS(app, resources={
    r"/ext/*": {
        "origins": ["chrome-extension://*", "http://localhost:*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# =============================================================================
# Configuration
# =============================================================================

# Storage paths - must match server.py and Conversation.py
# server.py uses: os.path.join(os.getcwd(), "storage", "users") for users_dir
# Conversation.py uses: os.path.join(os.path.dirname(__file__), "storage", "users", "pkb.sqlite")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STORAGE_USERS_DIR = os.path.join(PROJECT_ROOT, "storage", "users")
USERS_DIR = os.getenv("USERS_DIR", os.path.join(PROJECT_ROOT, "users"))

# Extension-specific storage
EXTENSION_DB_PATH = os.path.join(USERS_DIR, "extension.db")

# Shared storage paths (same as Conversation.py and server.py)
PKB_DB_PATH = os.path.join(STORAGE_USERS_DIR, "pkb.sqlite")
USER_DETAILS_DB_PATH = os.path.join(USERS_DIR, "users.db")
PROMPTS_FILE = os.path.join(PROJECT_ROOT, "prompts.json")

# Ensure directories exist
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(STORAGE_USERS_DIR, exist_ok=True)

# =============================================================================
# Import Extension Module Components
# =============================================================================

try:
    from extension import (
        ExtensionAuth, ExtensionDB, ExtensionConversation,
        init_extension_paths, keyParser_for_extension
    )
    init_extension_paths(USERS_DIR, os.path.join(USERS_DIR, "extension_conversations"))
    logger.info("Extension module loaded successfully")
except ImportError as e:
    logger.error(f"Failed to import extension module: {e}")
    raise

# =============================================================================
# Import Prompt Library (Read-Only)
# =============================================================================

try:
    from prompt_lib import create_wrapped_manager
    prompt_manager = create_wrapped_manager(PROMPTS_FILE)
    logger.info(f"Prompt library loaded from {PROMPTS_FILE}")
except ImportError as e:
    logger.warning(f"Prompt library not available: {e}")
    prompt_manager = None
except Exception as e:
    logger.warning(f"Failed to load prompts from {PROMPTS_FILE}: {e}")
    prompt_manager = None

# =============================================================================
# Import Truth Management System / PKB (Read-Only)
# =============================================================================

try:
    from truth_management_system import (
        PKBConfig, get_database, StructuredAPI
    )
    PKB_AVAILABLE = True
    _pkb_db = None
    _pkb_config = None
    logger.info("Truth Management System (PKB) available")
except ImportError as e:
    logger.warning(f"PKB not available: {e}")
    PKB_AVAILABLE = False

# =============================================================================
# Import LLM Calling Module
# =============================================================================

try:
    from code_common.call_llm import call_llm, get_query_embedding
    LLM_AVAILABLE = True
    logger.info("LLM module (code_common/call_llm) loaded")
except ImportError as e:
    logger.warning(f"LLM module not available: {e}")
    LLM_AVAILABLE = False

# =============================================================================
# Database Connection Helper
# =============================================================================

def create_connection(db_path):
    """
    Create a database connection to a SQLite database.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        sqlite3.Connection or None if connection fails
    """
    import sqlite3
    try:
        return sqlite3.connect(db_path)
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

# =============================================================================
# Database & PKB Helpers
# =============================================================================

def get_extension_db() -> ExtensionDB:
    """Get ExtensionDB instance."""
    return ExtensionDB(EXTENSION_DB_PATH)


def get_pkb_db():
    """Get or initialize the shared PKB database instance."""
    global _pkb_db, _pkb_config
    
    if not PKB_AVAILABLE:
        return None, None
    
    if _pkb_db is None:
        _pkb_config = PKBConfig(db_path=PKB_DB_PATH)
        _pkb_db = get_database(_pkb_config)
        logger.info(f"Initialized PKB database at {PKB_DB_PATH}")
    
    return _pkb_db, _pkb_config


def get_pkb_api_for_user(user_email: str, keys: dict = None) -> Optional[StructuredAPI]:
    """Get a StructuredAPI instance scoped to a specific user."""
    db, config = get_pkb_db()
    if db is None:
        return None
    return StructuredAPI(db, keys or {}, config, user_email=user_email)


def verify_user_credentials(email: str, password: str) -> bool:
    """
    Verify user credentials against the user details database.
    
    Uses same password hash logic as the main server.
    """
    try:
        conn = create_connection(USER_DETAILS_DB_PATH)
        if conn is None:
            # If no user database, check environment password
            return password == os.getenv("PASSWORD", "XXXX")
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT password_hash FROM UserDetails WHERE email = ?
        """, (email,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            # No user found, check environment password
            return password == os.getenv("PASSWORD", "XXXX")
        
        if row[0]:
            # User has password hash, verify it
            from hashlib import sha256
            password_hash = sha256(password.encode()).hexdigest()
            return password_hash == row[0]
        else:
            # No password hash, use environment password
            return password == os.getenv("PASSWORD", "XXXX")
            
    except Exception as e:
        logger.error(f"Error verifying credentials: {e}")
        # Fallback to environment password
        return password == os.getenv("PASSWORD", "XXXX")


def get_user_details(email: str) -> Optional[Dict]:
    """Get user details from database."""
    try:
        conn = create_connection(USER_DETAILS_DB_PATH)
        if conn is None:
            return None
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT email, name, created_at FROM UserDetails WHERE email = ?
        """, (email,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'email': row[0],
                'name': row[1] or email.split('@')[0],
                'created_at': row[2]
            }
        return None
    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return None


def add_user_to_details(email: str, name: str = None):
    """Add user to details table if not exists."""
    try:
        conn = create_connection(USER_DETAILS_DB_PATH)
        if conn is None:
            return False
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO UserDetails (email, name, created_at)
            VALUES (?, ?, ?)
        """, (email, name or email.split('@')[0], datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding user details: {e}")
        return False


def serialize_claim(claim) -> Dict:
    """Convert a Claim object to JSON-serializable dict."""
    return {
        'claim_id': claim.claim_id,
        'user_email': claim.user_email,
        'claim_type': claim.claim_type,
        'statement': claim.statement,
        'context_domain': claim.context_domain,
        'status': claim.status,
        'confidence': claim.confidence,
        'created_at': claim.created_at,
        'updated_at': claim.updated_at
    }


# =============================================================================
# Authentication Decorator
# =============================================================================

def require_ext_auth(f):
    """
    Decorator to protect extension endpoints with JWT authentication.
    
    Expects: Authorization: Bearer <token> header
    Injects: request.ext_user_email with authenticated user's email
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid authorization header'}), 401
        
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        valid, payload = ExtensionAuth.verify_token(token)
        
        if not valid:
            return jsonify({'error': payload.get('error', 'Invalid token')}), 401
        
        # Inject user email into request context
        request.ext_user_email = payload['email']
        return f(*args, **kwargs)
    
    return decorated


# =============================================================================
# Authentication Endpoints
# =============================================================================

@app.route('/ext/auth/login', methods=['POST'])
def ext_login():
    """
    Login and receive JWT token.
    
    Request body:
        {"email": "user@example.com", "password": "password"}
    
    Response:
        {"token": "jwt_token_string", "email": "user@example.com", "name": "User"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        # Verify credentials
        if not verify_user_credentials(email, password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Ensure user exists in details table
        user_details = get_user_details(email)
        if not user_details:
            add_user_to_details(email)
            user_details = {'email': email, 'name': email.split('@')[0]}
        
        # Generate token
        token = ExtensionAuth.generate_token(email)
        
        return jsonify({
            'token': token,
            'email': email,
            'name': user_details.get('name', email.split('@')[0])
        })
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/auth/logout', methods=['POST'])
@require_ext_auth
def ext_logout():
    """
    Logout (invalidate token).
    
    Note: Since we use stateless JWT, this is mostly a client-side operation.
    Client should delete the token from chrome.storage.
    """
    ExtensionAuth.invalidate_token(request.headers.get('Authorization', '')[7:])
    return jsonify({'message': 'Logged out successfully'})


@app.route('/ext/auth/verify', methods=['POST'])
def ext_verify_token():
    """
    Verify token validity.
    
    Request headers:
        Authorization: Bearer <token>
    
    Response:
        {"valid": true, "email": "user@example.com"} or
        {"valid": false, "error": "Token expired"}
    """
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        return jsonify({'valid': False, 'error': 'Missing token'}), 200
    
    token = auth_header[7:]
    valid, payload = ExtensionAuth.verify_token(token)
    
    if valid:
        return jsonify({'valid': True, 'email': payload['email']})
    else:
        return jsonify({'valid': False, 'error': payload.get('error', 'Invalid token')})


# =============================================================================
# Prompt Endpoints (Read-Only)
# =============================================================================

@app.route('/ext/prompts', methods=['GET'])
@require_ext_auth
def ext_list_prompts():
    """
    List available prompts.
    
    Returns:
        {"prompts": [{"name": "prompt_name", "description": "..."}, ...]}
    """
    if prompt_manager is None:
        return jsonify({'error': 'Prompt library not available'}), 503
    
    try:
        prompts = []
        for name in prompt_manager.keys():
            try:
                metadata = prompt_manager.get_raw(name, as_dict=True)
                prompts.append({
                    'name': name,
                    'description': metadata.get('description', ''),
                    'category': metadata.get('category', '')
                })
            except:
                prompts.append({'name': name, 'description': '', 'category': ''})
        
        return jsonify({'prompts': prompts})
        
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/prompts/<prompt_name>', methods=['GET'])
@require_ext_auth
def ext_get_prompt(prompt_name):
    """
    Get specific prompt content.
    
    Args:
        prompt_name: Name of the prompt to retrieve
    
    Returns:
        {"name": "prompt_name", "content": "composed prompt content", ...}
    """
    if prompt_manager is None:
        return jsonify({'error': 'Prompt library not available'}), 503
    
    try:
        if prompt_name not in prompt_manager:
            return jsonify({'error': f"Prompt '{prompt_name}' not found"}), 404
        
        # Get composed prompt content
        content = prompt_manager[prompt_name]
        
        # Try to get metadata
        try:
            metadata = prompt_manager.get_raw(prompt_name, as_dict=True)
            return jsonify({
                'name': prompt_name,
                'content': content,
                'raw_content': metadata.get('content', content),
                'description': metadata.get('description', ''),
                'category': metadata.get('category', ''),
                'tags': metadata.get('tags', [])
            })
        except:
            return jsonify({
                'name': prompt_name,
                'content': content,
                'raw_content': content
            })
            
    except Exception as e:
        logger.error(f"Error getting prompt '{prompt_name}': {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Memory/PKB Endpoints (Read-Only)
# =============================================================================

@app.route('/ext/memories', methods=['GET'])
@require_ext_auth
def ext_list_memories():
    """
    List user's memories (PKB claims).
    
    Query params:
        limit: Maximum number to return (default 50)
        offset: Pagination offset (default 0)
        status: Filter by status (default "active")
        claim_type: Filter by type (optional)
    
    Returns:
        {"memories": [...], "total": N}
    """
    if not PKB_AVAILABLE:
        return jsonify({'error': 'Memory system not available'}), 503
    
    try:
        email = request.ext_user_email
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        status = request.args.get('status', 'active')
        claim_type = request.args.get('claim_type')
        
        keys = keyParser_for_extension()
        api = get_pkb_api_for_user(email, keys)
        
        if api is None:
            return jsonify({'memories': [], 'total': 0})
        
        # Build filters dict (only include non-None values)
        filters = {}
        if status:
            filters['status'] = status
        if claim_type:
            filters['claim_type'] = claim_type
        
        # List claims
        result = api.claims.list(
            filters=filters if filters else None,
            limit=limit,
            offset=offset
        )
        
        memories = [serialize_claim(c) for c in result]
        
        return jsonify({
            'memories': memories,
            'total': len(memories)  # TODO: Add proper count
        })
        
    except Exception as e:
        logger.error(f"Error listing memories: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/memories/search', methods=['POST'])
@require_ext_auth
def ext_search_memories():
    """
    Search memories.
    
    Request body:
        {"query": "search text", "k": 10, "strategy": "hybrid"}
    
    Returns:
        {"results": [{"claim": {...}, "score": 0.95}, ...]}
    """
    if not PKB_AVAILABLE:
        return jsonify({'error': 'Memory system not available'}), 503
    
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        query = data.get('query', '')
        k = data.get('k', 10)
        strategy = data.get('strategy', 'hybrid')
        
        if not query:
            return jsonify({'error': 'Query required'}), 400
        
        keys = keyParser_for_extension()
        api = get_pkb_api_for_user(email, keys)
        
        if api is None:
            return jsonify({'results': []})
        
        # Search
        result = api.search(query, k=k, strategy=strategy)
        
        if result.success:
            results = [
                {
                    'claim': serialize_claim(r.claim),
                    'score': r.score
                }
                for r in result.data
            ]
            return jsonify({'results': results})
        else:
            return jsonify({'results': [], 'warnings': result.warnings})
        
    except Exception as e:
        logger.error(f"Error searching memories: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/memories/<claim_id>', methods=['GET'])
@require_ext_auth
def ext_get_memory(claim_id):
    """
    Get specific memory by ID.
    
    Args:
        claim_id: ID of the claim to retrieve
    
    Returns:
        {"memory": {...}}
    """
    if not PKB_AVAILABLE:
        return jsonify({'error': 'Memory system not available'}), 503
    
    try:
        email = request.ext_user_email
        keys = keyParser_for_extension()
        api = get_pkb_api_for_user(email, keys)
        
        if api is None:
            return jsonify({'error': 'Memory system not available'}), 503
        
        result = api.get_claim(claim_id)
        
        if result.success and result.data:
            return jsonify({'memory': serialize_claim(result.data)})
        else:
            return jsonify({'error': 'Memory not found'}), 404
        
    except Exception as e:
        logger.error(f"Error getting memory: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/memories/pinned', methods=['GET'])
@require_ext_auth
def ext_get_pinned_memories():
    """
    Get globally pinned memories for the user.
    
    Returns:
        {"memories": [...]}
    """
    if not PKB_AVAILABLE:
        return jsonify({'error': 'Memory system not available'}), 503
    
    try:
        email = request.ext_user_email
        keys = keyParser_for_extension()
        api = get_pkb_api_for_user(email, keys)
        
        if api is None:
            return jsonify({'memories': []})
        
        result = api.get_pinned_claims(limit=50)
        
        if result.success:
            memories = [serialize_claim(c) for c in result.data]
            return jsonify({'memories': memories})
        else:
            return jsonify({'memories': []})
        
    except Exception as e:
        logger.error(f"Error getting pinned memories: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Conversation Endpoints
# =============================================================================

@app.route('/ext/conversations', methods=['GET'])
@require_ext_auth
def ext_list_conversations():
    """
    List user's conversations.
    
    Query params:
        limit: Maximum number (default 50)
        offset: Pagination offset (default 0)
        include_temporary: Include temporary convs (default true)
    
    Returns:
        {"conversations": [...], "total": N}
    """
    try:
        email = request.ext_user_email
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        include_temporary = request.args.get('include_temporary', 'true').lower() == 'true'
        
        db = get_extension_db()
        conversations = db.list_conversations(
            email, 
            limit=limit, 
            offset=offset,
            include_temporary=include_temporary
        )
        total = db.count_conversations(email)
        
        return jsonify({
            'conversations': conversations,
            'total': total
        })
        
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/conversations', methods=['POST'])
@require_ext_auth
def ext_create_conversation():
    """
    Create new conversation.
    
    Request body:
        {
            "title": "Optional title",
            "is_temporary": true,
            "model": "openai/gpt-4o-mini",
            "prompt_name": "Short",
            "history_length": 10
        }
    
    Returns:
        {"conversation": {...}, "deleted_temporary": <count>}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        db = get_extension_db()
        
        # Delete old temporary conversations before creating a new one
        deleted_count = 0
        if data.get('delete_temporary', True):  # Default to true
            deleted_count = db.delete_temporary_conversations(email)
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} temporary conversations for {email}")
        
        conv = ExtensionConversation.create(
            user_email=email,
            db=db,
            title=data.get('title', 'New Chat'),
            is_temporary=data.get('is_temporary', True),
            model=data.get('model', 'openai/gpt-4o-mini'),
            prompt_name=data.get('prompt_name'),
            history_length=data.get('history_length', 10)
        )
        
        return jsonify({
            'conversation': conv.to_dict(),
            'deleted_temporary': deleted_count
        })
        
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/conversations/<conversation_id>', methods=['GET'])
@require_ext_auth
def ext_get_conversation(conversation_id):
    """
    Get conversation details with messages.
    
    Args:
        conversation_id: ID of the conversation
    
    Returns:
        {"conversation": {..., "messages": [...]}}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        return jsonify({'conversation': conv.to_dict()})
        
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/conversations/<conversation_id>', methods=['PUT'])
@require_ext_auth
def ext_update_conversation(conversation_id):
    """
    Update conversation metadata.
    
    Request body:
        {"title": "New title", "is_temporary": false, ...}
    
    Returns:
        {"conversation": {...}}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        db = get_extension_db()
        
        # Verify ownership
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Update allowed fields
        success = db.update_conversation(conversation_id, email, **data)
        
        if success:
            conv = ExtensionConversation.load(conversation_id, email, db)
            return jsonify({'conversation': conv.to_dict()})
        else:
            return jsonify({'error': 'Update failed'}), 500
        
    except Exception as e:
        logger.error(f"Error updating conversation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/conversations/<conversation_id>/save', methods=['POST'])
@require_ext_auth
def ext_save_conversation(conversation_id):
    """
    Save a conversation (mark as non-temporary).
    Saved conversations won't be auto-deleted when new conversations are created.
    
    Args:
        conversation_id: ID of the conversation to save
    
    Returns:
        {"conversation": {...}, "message": "Conversation saved"}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        # Verify ownership
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Mark as non-temporary
        success = db.update_conversation(conversation_id, email, is_temporary=False)
        
        if success:
            conv = ExtensionConversation.load(conversation_id, email, db)
            return jsonify({
                'conversation': conv.to_dict(),
                'message': 'Conversation saved'
            })
        else:
            return jsonify({'error': 'Save failed'}), 500
        
    except Exception as e:
        logger.error(f"Error saving conversation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/conversations/<conversation_id>', methods=['DELETE'])
@require_ext_auth
def ext_delete_conversation(conversation_id):
    """
    Delete conversation.
    
    Args:
        conversation_id: ID of the conversation to delete
    
    Returns:
        {"message": "Deleted successfully"}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        success = db.delete_conversation(conversation_id, email)
        
        if success:
            return jsonify({'message': 'Deleted successfully'})
        else:
            return jsonify({'error': 'Conversation not found'}), 404
        
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Chat Endpoints
# =============================================================================

@app.route('/ext/chat/<conversation_id>', methods=['POST'])
@require_ext_auth
def ext_chat(conversation_id):
    """
    Send message and get LLM response.
    
    Request body:
        {
            "message": "User's message",
            "page_context": {"url": "...", "title": "...", "content": "..."},
            "model": "openai/gpt-4o-mini",  # Optional override
            "stream": true  # Whether to stream response
        }
    
    Returns (non-streaming):
        {"response": "Assistant's response", "message_id": "..."}
    
    Returns (streaming):
        Server-sent events with chunks
    """
    if not LLM_AVAILABLE:
        return jsonify({'error': 'LLM service not available'}), 503
    
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'error': 'Message required'}), 400
        
        page_context = data.get('page_context')
        model_override = data.get('model')
        stream = data.get('stream', False)
        
        db = get_extension_db()
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Add user message
        user_msg = conv.add_message('user', message, page_context)
        
        # Get system prompt
        system_prompt = None
        prompt_name = conv.prompt_name or 'base_system'
        if prompt_manager and prompt_name in prompt_manager:
            system_prompt = prompt_manager[prompt_name]
        else:
            system_prompt = "You are a helpful AI assistant."
        
        # Get PKB context
        keys = keyParser_for_extension()
        pkb_context = ""
        if PKB_AVAILABLE:
            try:
                api = get_pkb_api_for_user(email, keys)
                if api:
                    result = api.search(message, k=5, strategy='hybrid')
                    if result.success and result.data:
                        memories = [f"- {r.claim.statement}" for r in result.data[:5]]
                        if memories:
                            pkb_context = "\n\n[Relevant memories from user's knowledge base:]\n" + "\n".join(memories)
            except Exception as e:
                logger.warning(f"PKB context retrieval failed: {e}")
        
        # Build full system prompt
        full_system = system_prompt
        if pkb_context:
            full_system += pkb_context
        
        # Get history for LLM
        messages = [{"role": "system", "content": full_system}]
        
        # Add page context as a separate user message for better grounding
        logger.info(f"Page context received: hasContent={bool(page_context.get('content') if page_context else False)}, "
                   f"isMultiTab={page_context.get('isMultiTab') if page_context else None}, "
                   f"tabCount={page_context.get('tabCount') if page_context else None}, "
                   f"contentLength={len(page_context.get('content', '')) if page_context else 0}")
        if page_context:
            # Check if this is a screenshot (canvas-based app like Google Docs)
            if page_context.get('isScreenshot') and page_context.get('screenshot'):
                # Handle screenshot - build multimodal message
                screenshot_data = page_context.get('screenshot', '')
                # Remove data URL prefix if present (e.g., "data:image/png;base64,")
                if screenshot_data.startswith('data:'):
                    screenshot_data = screenshot_data.split(',', 1)[1] if ',' in screenshot_data else screenshot_data
                
                page_context_msg = {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"""I'm currently viewing this web page (screenshot provided because it uses canvas rendering):

**URL:** {page_context.get('url', 'N/A')}
**Title:** {page_context.get('title', 'N/A')}

⚠️ **Note:** This page (like Google Docs) uses canvas rendering, so I'm providing a screenshot instead of text. Please analyze the screenshot image below to understand the content.

---
Please use the screenshot to answer my questions. Base your response on what you can see in the image."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_data}"
                            }
                        }
                    ]
                }
                messages.append(page_context_msg)
                messages.append({"role": "assistant", "content": "I can see the screenshot of the page. I'll analyze the visible content to answer your questions. Note that some text may not be perfectly readable depending on image quality. What would you like to know?"})
                
            elif page_context.get('content'):
                # Regular text content (may be single page or multi-tab)
                page_content = page_context.get('content', '')
                is_multi_tab = page_context.get('isMultiTab', False)
                tab_count = page_context.get('tabCount', 1)
                
                # Maximum content size - 128K for multi-tab (split among tabs), 64K for single
                max_content_size = 128000 if is_multi_tab else 64000
                
                if len(page_content) > max_content_size:
                    if is_multi_tab and tab_count > 1:
                        # For multi-tab: truncate each tab section proportionally
                        # Split by the separator we use: "\n\n---\n\n"
                        tab_sections = page_content.split('\n\n---\n\n')
                        chars_per_tab = max_content_size // tab_count
                        truncated_sections = []
                        for section in tab_sections:
                            if len(section) > chars_per_tab:
                                truncated_sections.append(section[:chars_per_tab] + "\n\n[... content truncated ...]")
                            else:
                                truncated_sections.append(section)
                        page_content = '\n\n---\n\n'.join(truncated_sections)
                        logger.info(f"Multi-tab content truncated: {tab_count} tabs, ~{chars_per_tab} chars each")
                    else:
                        # Single page: simple truncation
                        page_content = page_content[:max_content_size] + "\n\n[Content truncated...]"
                
                if is_multi_tab and tab_count > 1:
                    page_context_msg = f"""I'm currently viewing content from **{tab_count} browser tabs**:

{page_content}

---
Please use the content from all {tab_count} tabs above to answer my questions. Each tab's content is separated by headers showing the tab title and URL."""
                    assistant_ack = f"I've read the content from all {tab_count} tabs. I'll use this combined information to answer your questions. What would you like to know?"
                else:
                    page_context_msg = f"""I'm currently viewing this web page:

**URL:** {page_context.get('url', 'N/A')}
**Title:** {page_context.get('title', 'N/A')}

**Page Content:**
{page_content}

---
Please use the above page content to answer my questions. Base your response on the actual content from this page."""
                    assistant_ack = "I've read the page content. I'll use it to answer your questions accurately. What would you like to know?"
                
                logger.info(f"Adding page context to messages: isMultiTab={is_multi_tab}, tabCount={tab_count}, msgLength={len(page_context_msg)}")
                messages.append({"role": "user", "content": page_context_msg})
                messages.append({"role": "assistant", "content": assistant_ack})
        
        messages.extend(conv.get_history_for_llm())
        
        # Determine model
        model = model_override or conv.model or DEFAULT_MODEL
        
        if stream:
            # Streaming response
            def generate():
                full_response = []
                try:
                    for chunk in call_llm(
                        keys=keys,
                        model_name=model,
                        messages=messages,
                        stream=True
                    ):
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                    
                    # Save assistant message
                    assistant_content = ''.join(full_response)
                    assistant_msg = conv.add_message('assistant', assistant_content)
                    yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['message_id']})}\n\n"
                    
                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no'
                }
            )
        else:
            # Non-streaming response
            response = call_llm(
                keys=keys,
                model_name=model,
                messages=messages,
                stream=False
            )
            
            # Save assistant message
            assistant_msg = conv.add_message('assistant', response)
            
            return jsonify({
                'response': response,
                'message_id': assistant_msg['message_id'],
                'user_message_id': user_msg['message_id']
            })
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/chat/<conversation_id>/message', methods=['POST'])
@require_ext_auth
def ext_add_message(conversation_id):
    """
    Add a message without LLM response.
    
    Useful for adding system messages or imported content.
    
    Request body:
        {"role": "user|assistant", "content": "message content"}
    
    Returns:
        {"message": {...}}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        role = data.get('role', 'user')
        content = data.get('content', '').strip()
        page_context = data.get('page_context')
        
        if not content:
            return jsonify({'error': 'Content required'}), 400
        
        if role not in ('user', 'assistant', 'system'):
            return jsonify({'error': 'Invalid role'}), 400
        
        db = get_extension_db()
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        msg = conv.add_message(role, content, page_context)
        
        return jsonify({'message': msg})
        
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/chat/<conversation_id>/messages/<message_id>', methods=['DELETE'])
@require_ext_auth
def ext_delete_message(conversation_id, message_id):
    """
    Delete a message.
    
    Args:
        conversation_id: Conversation ID
        message_id: Message ID to delete
    
    Returns:
        {"message": "Deleted successfully"}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        success = db.delete_message(conversation_id, message_id, email)
        
        if success:
            return jsonify({'message': 'Deleted successfully'})
        else:
            return jsonify({'error': 'Message not found'}), 404
        
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Settings Endpoints
# =============================================================================

@app.route('/ext/settings', methods=['GET'])
@require_ext_auth
def ext_get_settings():
    """
    Get user's extension settings.
    
    Returns:
        {"settings": {"default_model": "...", ...}}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        settings = db.get_settings(email)
        
        return jsonify({'settings': settings})
        
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/settings', methods=['PUT'])
@require_ext_auth
def ext_update_settings():
    """
    Update user's extension settings.
    
    Request body:
        {"default_model": "...", "history_length": 20, ...}
    
    Returns:
        {"settings": {...}}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        db = get_extension_db()
        
        db.update_settings(email, **data)
        settings = db.get_settings(email)
        
        return jsonify({'settings': settings})
        
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Utility Endpoints
# =============================================================================

# =============================================================================
# Available LLM Models - Update this list to add new models
# =============================================================================

AVAILABLE_MODELS = [
    "google/gemini-2.5-flash",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.5",
    "openai/gpt-5.2",
    "google/gemini-3-pro-preview",
]

# Default model if none specified
DEFAULT_MODEL = "google/gemini-2.5-flash"


def get_model_display_name(model_id: str) -> str:
    """Extract display name from model ID (part after /)."""
    if '/' in model_id:
        return model_id.split('/', 1)[1]
    return model_id


def get_model_provider(model_id: str) -> str:
    """Extract provider from model ID (part before /)."""
    if '/' in model_id:
        return model_id.split('/', 1)[0].title()
    return "Unknown"


@app.route('/ext/models', methods=['GET'])
@require_ext_auth
def ext_list_models():
    """
    List available LLM models.
    
    Returns:
        {"models": [{"id": "google/gemini-2.5-flash", "name": "gemini-2.5-flash", "provider": "Google"}, ...]}
    """
    models = [
        {
            "id": model_id,
            "name": get_model_display_name(model_id),
            "provider": get_model_provider(model_id)
        }
        for model_id in AVAILABLE_MODELS
    ]
    
    return jsonify({'models': models, 'default': DEFAULT_MODEL})


@app.route('/ext/health', methods=['GET'])
def ext_health():
    """
    Health check endpoint.
    
    Returns:
        {"status": "healthy", "services": {...}}
    """
    return jsonify({
        'status': 'healthy',
        'services': {
            'prompt_lib': prompt_manager is not None,
            'pkb': PKB_AVAILABLE,
            'llm': LLM_AVAILABLE
        },
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extension Server')
    parser.add_argument('--port', type=int, default=5001, help='Port to run on')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    logger.info(f"Starting Extension Server on {args.host}:{args.port}")
    logger.info(f"Prompts available: {prompt_manager is not None}")
    logger.info(f"PKB available: {PKB_AVAILABLE}")
    logger.info(f"LLM available: {LLM_AVAILABLE}")
    
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=True
    )

