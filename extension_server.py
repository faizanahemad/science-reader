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
import inspect
import types
import collections.abc
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from queue import Queue
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# OCR / Vision configuration
OCR_VISION_MODEL = os.getenv("EXT_OCR_MODEL", "openai/gpt-4o")
OCR_MAX_IMAGES = int(os.getenv("EXT_OCR_MAX_IMAGES", "30"))
OCR_MAX_WORKERS = int(os.getenv("EXT_OCR_MAX_WORKERS", "4"))

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
# Extension Prompt Allowlist
# =============================================================================

# Keep this list focused on prompts intended for the extension UI.
# If empty, all prompts from prompts.json are allowed.
EXTENSION_PROMPT_ALLOWLIST = [
    "base_system",
    "preamble_short",
    "relationship_prompt",
    "short_coding_interview_prompt",
    "more_related_questions_prompt",
    "default",
    
]


def get_extension_prompt_allowlist() -> Optional[set]:
    """
    Return the allowlist of prompt names for the extension.

    Returns:
        set of allowed prompt names, or None to allow all prompts.
    """
    allowlist = [name for name in EXTENSION_PROMPT_ALLOWLIST if name]
    return set(allowlist) if allowlist else None


def get_default_prompt_name() -> str:
    """
    Get the default prompt name for the extension UI.

    Returns:
        A prompt name that is allowed and likely present in prompts.json.
    """
    allowlist = get_extension_prompt_allowlist()
    if not allowlist:
        return "base_system"
    if "Short" in allowlist:
        return "Short"
    if "preamble_short" in allowlist:
        return "preamble_short"
    
    return sorted(allowlist)[0]


def validate_prompt_name(prompt_name: Optional[str]) -> Optional[str]:
    """
    Validate a prompt name against the allowlist and prompt library.

    Args:
        prompt_name: The prompt name to validate.

    Returns:
        None if valid, otherwise an error message.
    """
    if not prompt_name:
        return None

    allowlist = get_extension_prompt_allowlist()
    if allowlist and prompt_name not in allowlist:
        return f"Prompt '{prompt_name}' is not available for the extension."

    if prompt_manager and prompt_name not in prompt_manager:
        return f"Prompt '{prompt_name}' not found."

    return None

# =============================================================================
# Extension Agent Allowlist
# =============================================================================

# Allowed agents for extension usage (based on interface.html Agent dropdown).
# Keep this list to agents that are supported in Conversation.get_preamble().
EXTENSION_AGENT_ALLOWLIST = [
    "None",
    "NStepCodeAgent",
    "PerplexitySearch",
    "JinaSearchAgent",
    "InterleavedWebSearchAgent",
    "WebSearch",
    "MultiSourceSearch",
    "PromptWorkflowAgent",
    "ManagerAssistAgent",
]


def get_extension_agent_allowlist() -> Optional[set]:
    """
    Return the allowlist of agent names for the extension.

    Returns:
        set of allowed agent names, or None to allow all agents.
    """
    allowlist = [name for name in EXTENSION_AGENT_ALLOWLIST if name]
    return set(allowlist) if allowlist else None


def validate_agent_name(agent_name: Optional[str]) -> Optional[str]:
    """
    Validate an agent name against the allowlist.

    Args:
        agent_name: Agent name to validate (or None/"None" to disable).

    Returns:
        None if valid, otherwise an error message.
    """
    if not agent_name or agent_name == "None":
        return None

    allowlist = get_extension_agent_allowlist()
    if allowlist and agent_name not in allowlist:
        return f"Agent '{agent_name}' is not available for the extension."

    return None


def instantiate_extension_agent(
    agent_name: str,
    model_name: str,
    keys: dict,
    conversation_id: str,
    detail_level: int = 1
):
    """
    Instantiate an agent compatible with Conversation.get_preamble() selections.

    Args:
        agent_name: Agent name from allowlist.
        model_name: Model name to use for the agent.
        keys: LLM API keys/config.
        conversation_id: Conversation id (used by some agents).
        detail_level: Detail level for agent behavior.

    Returns:
        Agent instance or None.
    """
    if not agent_name or agent_name == "None":
        return None

    # Import lazily to avoid startup overhead
    from agents import (
        NResponseAgent,
        InstructionFollowingAgent,
        MLSystemDesignAgent,
        CodeSolveAgent,
        NStepCodeAgent,
        WebSearchWithAgent,
        MultiSourceSearchAgent,
        BroadSearchAgent,
        LiteratureReviewAgent,
        PerplexitySearchAgent,
        WhatIfAgent,
        JinaDeepResearchAgent,
        BookCreatorAgent,
        ToCGenerationAgent,
        InterviewSimulatorAgent,
        InterviewSimulatorAgentV2,
        PromptWorkflowAgent,
        ManagerAssistAgent,
    )
    from agents.search_and_information_agents import (
        JinaSearchAgent,
        InterleavedWebSearchAgent
    )

    if agent_name == "InstructionFollowingAgent":
        return InstructionFollowingAgent(keys, model_name=model_name, detail_level=detail_level, timeout=90)
    if agent_name == "JinaSearchAgent":
        return JinaSearchAgent(keys, model_name=model_name, detail_level=detail_level, timeout=120)
    if agent_name == "InterleavedWebSearchAgent":
        return InterleavedWebSearchAgent(
            keys,
            model_name=model_name,
            detail_level=detail_level,
            timeout=120,
            num_queries_per_step=3,
            interleave_steps=3,
            sources=["web", "perplexity", "jina"],
            show_intermediate_results=False,
            headless=False
        )
    if agent_name == "JinaDeepResearchAgent":
        return JinaDeepResearchAgent(keys, model_name=model_name, detail_level=detail_level, timeout=180, num_queries=1)
    if agent_name == "PerplexitySearch":
        return PerplexitySearchAgent(keys, model_name=model_name, detail_level=detail_level, timeout=90)
    if agent_name == "WebSearch":
        return WebSearchWithAgent(keys, model_name=model_name, detail_level=detail_level, timeout=90, gscholar=False)
    if agent_name == "MultiSourceSearch":
        return MultiSourceSearchAgent(keys, model_name=model_name, detail_level=detail_level, timeout=120)
    if agent_name == "LiteratureReview":
        return LiteratureReviewAgent(keys, model_name=model_name, detail_level=detail_level, timeout=90, gscholar=False)
    if agent_name == "BroadSearch":
        return BroadSearchAgent(keys, model_name=model_name, detail_level=detail_level, timeout=90, gscholar=False)
    if agent_name == "InterviewSimulator":
        return InterviewSimulatorAgent(keys, writer_model=model_name, conversation_id=conversation_id, detail_level=detail_level, timeout=90)
    if agent_name == "InterviewSimulatorV2":
        return InterviewSimulatorAgentV2(keys, writer_model=model_name, conversation_id=conversation_id, detail_level=detail_level, timeout=90)
    if agent_name == "NResponseAgent":
        return NResponseAgent(keys, writer_model=model_name, n_responses=2)
    if agent_name == "NStepCodeAgent":
        return NStepCodeAgent(keys, writer_model=model_name, n_steps=detail_level or 4)
    if agent_name == "CodeSolveAgent":
        return CodeSolveAgent(keys, writer_model=model_name, n_steps=max(2, detail_level or 2))
    if agent_name == "MLSystemDesignAgent":
        return MLSystemDesignAgent(keys, writer_model=model_name, n_steps=detail_level or 4)
    if agent_name == "PromptWorkflowAgent":
        return PromptWorkflowAgent(keys, model_name=model_name)
    if agent_name == "ManagerAssistAgent":
        return ManagerAssistAgent(keys, model_name=model_name)
    if agent_name == "ToCGenerationAgent":
        return ToCGenerationAgent(
            llm_name=model_name,
            keys=keys,
            run_phase_2=(detail_level or 1) > 2,
            run_phase_3=(detail_level or 1) > 3,
            storage_path=os.path.join(PROJECT_ROOT, "users"),
            render_prefix=""
        )
    if agent_name == "BookCreatorAgent":
        return BookCreatorAgent(
            llm_name=model_name,
            keys=keys,
            depth=detail_level or 1,
            storage_path=os.path.join(PROJECT_ROOT, "users"),
            render_prefix=""
        )
    if agent_name == "WhatIf":
        return WhatIfAgent(keys, writer_models=model_name, n_scenarios=3)

    return None


def build_agent_prompt_from_history(history: List[Dict], page_context: Optional[Dict]) -> str:
    """
    Build a prompt string for agent execution using message history and page context.

    Args:
        history: LLM-formatted message history (role/content).
        page_context: Optional page context dict.

    Returns:
        Combined prompt string.
    """
    parts = []
    if page_context:
        content = page_context.get("content") or ""
        if content:
            parts.append(
                "Page Context:\n"
                f"URL: {page_context.get('url', 'N/A')}\n"
                f"Title: {page_context.get('title', 'N/A')}\n"
                f"Content:\n{content}"
            )
    if history:
        history_lines = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            history_lines.append(f"{role.title()}: {content}")
        parts.append("Conversation History:\n" + "\n".join(history_lines))
    return "\n\n".join(parts).strip()


def validate_workflow_steps(steps: Any) -> Optional[str]:
    """
    Validate workflow steps payload.

    Args:
        steps: Steps payload (expected list of {title, prompt}).

    Returns:
        None if valid, otherwise error message.
    """
    if not isinstance(steps, list) or len(steps) == 0:
        return "Workflow steps must be a non-empty list."
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"Step {idx + 1} must be an object."
        title = (step.get("title") or "").strip()
        prompt = (step.get("prompt") or "").strip()
        if not title:
            return f"Step {idx + 1} title is required."
        if not prompt:
            return f"Step {idx + 1} prompt is required."
    return None


def build_workflow_user_query(message: str, page_context: Optional[Dict]) -> str:
    """
    Build a user query string for workflow execution.

    Args:
        message: The user message text.
        page_context: Optional page context dict.

    Returns:
        Combined user query string.
    """
    parts = [message]
    if page_context and page_context.get("content"):
        parts.append(
            "Page Context:\n"
            f"URL: {page_context.get('url', 'N/A')}\n"
            f"Title: {page_context.get('title', 'N/A')}\n"
            f"Content:\n{page_context.get('content', '')}"
        )
    return "\n\n".join([p for p in parts if p]).strip()


def format_workflow_chunk(chunk: str, step_titles: List[str]) -> str:
    """
    Post-process streamed workflow chunks to replace step headers and remove prompt echoes.

    Args:
        chunk: Raw chunk string from PromptWorkflowAgent.
        step_titles: List of step titles by index.

    Returns:
        Transformed chunk text (may be empty to skip).
    """
    if not chunk:
        return ""
    if chunk.startswith("Prompt:\n"):
        return ""
    match = re.search(r"### Workflow step (\d+)/(\d+)", chunk)
    if match:
        idx = int(match.group(1)) - 1
        title = step_titles[idx] if 0 <= idx < len(step_titles) else f"Step {idx + 1}"
        chunk = chunk.replace(match.group(0), f"### {title}")
    return chunk


def format_workflow_output(text: str, step_titles: List[str]) -> str:
    """
    Format non-streaming workflow output by removing prompt echoes and fixing headers.

    Args:
        text: Raw output text.
        step_titles: List of step titles by index.

    Returns:
        Formatted output.
    """
    if not text:
        return text
    text = re.sub(r"Prompt:\n.*?\n\n", "", text, flags=re.S)
    def _replace_header(match):
        idx = int(match.group(1)) - 1
        title = step_titles[idx] if 0 <= idx < len(step_titles) else f"Step {idx + 1}"
        return f"### {title}"
    text = re.sub(r"### Workflow step (\d+)/\d+", _replace_header, text)
    return text

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
        allowlist = get_extension_prompt_allowlist()
        for name in prompt_manager.keys():
            if allowlist and name not in allowlist:
                continue
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
        allowlist = get_extension_prompt_allowlist()
        if allowlist and prompt_name not in allowlist:
            return jsonify({'error': f"Prompt '{prompt_name}' not available for extension"}), 404

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
# Agent Endpoints (Read-Only)
# =============================================================================

@app.route('/ext/agents', methods=['GET'])
@require_ext_auth
def ext_list_agents():
    """
    List available agents for the extension.

    Returns:
        {"agents": ["AgentName", ...]}
    """
    allowlist = get_extension_agent_allowlist()
    agents = sorted(list(allowlist)) if allowlist else []
    return jsonify({'agents': agents})


# =============================================================================
# Workflow Endpoints
# =============================================================================

@app.route('/ext/workflows', methods=['GET'])
@require_ext_auth
def ext_list_workflows():
    """
    List workflows for the authenticated user.

    Returns:
        {"workflows": [ ... ]}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        workflows = db.list_workflows(email)
        return jsonify({'workflows': workflows})
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/workflows', methods=['POST'])
@require_ext_auth
def ext_create_workflow():
    """
    Create a new workflow.

    Request body:
        {"name": "...", "steps": [{"title": "...", "prompt": "..."}, ...]}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        steps = data.get('steps')

        if not name:
            return jsonify({'error': 'Workflow name is required'}), 400
        steps_error = validate_workflow_steps(steps)
        if steps_error:
            return jsonify({'error': steps_error}), 400

        db = get_extension_db()
        workflow = db.create_workflow(email, name, steps)
        return jsonify({'workflow': workflow})
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/workflows/<workflow_id>', methods=['GET'])
@require_ext_auth
def ext_get_workflow(workflow_id):
    """
    Get a workflow by ID.
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        workflow = db.get_workflow(email, workflow_id)
        if not workflow:
            return jsonify({'error': 'Workflow not found'}), 404
        return jsonify({'workflow': workflow})
    except Exception as e:
        logger.error(f"Error getting workflow: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/workflows/<workflow_id>', methods=['PUT'])
@require_ext_auth
def ext_update_workflow(workflow_id):
    """
    Update a workflow.

    Request body:
        {"name": "...", "steps": [{"title": "...", "prompt": "..."}, ...]}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        steps = data.get('steps')

        if not name:
            return jsonify({'error': 'Workflow name is required'}), 400
        steps_error = validate_workflow_steps(steps)
        if steps_error:
            return jsonify({'error': steps_error}), 400

        db = get_extension_db()
        success = db.update_workflow(email, workflow_id, name, steps)
        if not success:
            return jsonify({'error': 'Workflow not found'}), 404
        workflow = db.get_workflow(email, workflow_id)
        return jsonify({'workflow': workflow})
    except Exception as e:
        logger.error(f"Error updating workflow: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/workflows/<workflow_id>', methods=['DELETE'])
@require_ext_auth
def ext_delete_workflow(workflow_id):
    """
    Delete a workflow.
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        success = db.delete_workflow(email, workflow_id)
        if not success:
            return jsonify({'error': 'Workflow not found'}), 404
        return jsonify({'message': 'Workflow deleted'})
    except Exception as e:
        logger.error(f"Error deleting workflow: {e}")
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
        
        prompt_name = data.get('prompt_name')
        prompt_error = validate_prompt_name(prompt_name)
        if prompt_error:
            return jsonify({'error': prompt_error}), 400

        conv = ExtensionConversation.create(
            user_email=email,
            db=db,
            title=data.get('title', 'New Chat'),
            is_temporary=data.get('is_temporary', True),
            model=data.get('model', 'openai/gpt-4o-mini'),
            prompt_name=prompt_name,
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
        
        if 'prompt_name' in data:
            prompt_error = validate_prompt_name(data.get('prompt_name'))
            if prompt_error:
                return jsonify({'error': prompt_error}), 400

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
            "images": ["data:image/png;base64,..."],
            "model": "openai/gpt-4o-mini",  # Optional override
            "agent": "InstructionFollowingAgent",  # Optional agent override
            "detail_level": 1,  # Optional agent detail level
            "workflow_id": "workflow_id",  # Optional workflow to run
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
        images = data.get('images') or []
        if not message and not images:
            return jsonify({'error': 'Message required'}), 400
        if not message and images:
            message = '[Image attached]'
        
        page_context = data.get('page_context')
        workflow_id = data.get('workflow_id')
        agent_name = data.get('agent')
        detail_level = data.get('detail_level', 2)
        model_override = data.get('model')
        stream = data.get('stream', False)
        
        db = get_extension_db()
        conv = ExtensionConversation.load(conversation_id, email, db)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Add user message
        user_msg = conv.add_message('user', message, page_context)

        # Determine model (used for both LLM and agents)
        model = model_override or conv.model or DEFAULT_MODEL
        
        # Load workflow if provided
        workflow_steps = None
        workflow_titles = []
        if workflow_id:
            workflow = db.get_workflow(email, workflow_id)
            if not workflow:
                return jsonify({'error': 'Workflow not found'}), 404
            workflow_steps = workflow.get('steps') or []
            workflow_titles = [step.get('title', f"Step {i+1}") for i, step in enumerate(workflow_steps)]
            agent_name = "PromptWorkflowAgent"

        # Validate agent (if provided)
        agent_error = validate_agent_name(agent_name)
        if agent_error:
            return jsonify({'error': agent_error}), 400

        # Get system prompt
        system_prompt = None
        prompt_name = conv.prompt_name or get_default_prompt_name()
        prompt_error = validate_prompt_name(prompt_name)
        if prompt_error:
            logger.warning(f"Invalid prompt '{prompt_name}', falling back to default: {prompt_error}")
            prompt_name = get_default_prompt_name()
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

        if images:
            if not isinstance(images, list):
                return jsonify({'error': 'images must be a list of data URLs'}), 400
            if len(images) > 5:
                return jsonify({'error': 'Max 5 images per message'}), 400
            image_parts = [
                {"type": "image_url", "image_url": {"url": img}}
                for img in images if isinstance(img, str) and img
            ]
            if image_parts:
                messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": "Images attached for the user's latest message."}] + image_parts
                })
        
        if agent_name and agent_name != "None":
            agent = instantiate_extension_agent(agent_name, model, keys, conversation_id, detail_level=detail_level)
            if not agent:
                return jsonify({'error': f"Agent '{agent_name}' could not be initialized"}), 500
            agent_images = images if isinstance(images, list) else None
            if agent_name == "PromptWorkflowAgent" and workflow_steps:
                workflow_prompts = [step.get('prompt', '') for step in workflow_steps]
                agent_prompt = message
                workflow_user_query = build_workflow_user_query(message, page_context)
            else:
                workflow_prompts = None
                workflow_user_query = None
                agent_prompt = build_agent_prompt_from_history(conv.get_history_for_llm(), page_context)

            def _iter_agent_chunks(result):
                if isinstance(result, dict):
                    text = result.get("answer") or result.get("text") or str(result)
                    yield text
                elif inspect.isgenerator(result) or isinstance(result, (types.GeneratorType, collections.abc.Iterator)):
                    for chunk in result:
                        if isinstance(chunk, dict):
                            yield chunk.get("text") or chunk.get("answer") or str(chunk)
                        else:
                            yield str(chunk)
                else:
                    yield str(result)

            if stream:
                def generate():
                    full_response = []
                    try:
                        result = agent(
                            agent_prompt,
                            images=agent_images,
                            system=full_system,
                            temperature=0.3,
                            stream=True,
                            workflow_prompts=workflow_prompts,
                            user_query=workflow_user_query
                        )
                        for chunk in _iter_agent_chunks(result):
                            if agent_name == "PromptWorkflowAgent" and workflow_titles:
                                chunk = format_workflow_chunk(chunk, workflow_titles)
                            if not chunk:
                                continue
                            if not chunk:
                                continue
                            full_response.append(chunk)
                            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                        assistant_content = ''.join(full_response)
                        assistant_msg = conv.add_message('assistant', assistant_content)
                        yield f"data: {json.dumps({'done': True, 'message_id': assistant_msg['message_id']})}\n\n"
                    except Exception as e:
                        logger.error(f"Agent streaming error: {e}")
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
                result = agent(
                    agent_prompt,
                    images=agent_images,
                    system=full_system,
                    temperature=0.3,
                    stream=False,
                    workflow_prompts=workflow_prompts,
                    user_query=workflow_user_query
                )
                text = ''.join(_iter_agent_chunks(result))
                if agent_name == "PromptWorkflowAgent" and workflow_titles:
                    text = format_workflow_output(text, workflow_titles)
                assistant_msg = conv.add_message('assistant', text)
                return jsonify({
                    'response': text,
                    'message_id': assistant_msg['message_id'],
                    'user_message_id': user_msg['message_id']
                })

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
        if 'default_prompt' in data:
            prompt_error = validate_prompt_name(data.get('default_prompt'))
            if prompt_error:
                return jsonify({'error': prompt_error}), 400

        db = get_extension_db()
        
        db.update_settings(email, **data)
        settings = db.get_settings(email)
        
        return jsonify({'settings': settings})
        
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# OCR / Vision Endpoints
# =============================================================================

def _build_ocr_messages(image_data_url: str) -> List[Dict[str, Any]]:
    """
    Build LLM messages for OCR extraction from a single image.

    Args:
        image_data_url: Data URL (base64) for the screenshot.

    Returns:
        A list of message dicts for the LLM call.
    """
    system_prompt = (
        "You are an expert at OCR and document transcription. "
        "Extract all readable text from the image, preserve structure, "
        "and include headings, tables, lists, form labels, and section boundaries. "
        "If something is unreadable, note it briefly."
    )
    user_prompt = (
        "Perform OCR on this screenshot. Return only the extracted text and its "
        "document structure (e.g., headings, sections, tables, lists, and form fields), "
        "keeping the original reading order as best as possible."
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}}
            ]
        }
    ]


def _ocr_single_image(index: int, image_data_url: str, model: str, keys: dict) -> Dict[str, Any]:
    """
    OCR a single image using a vision-capable LLM.

    Args:
        index: Image index in the batch.
        image_data_url: Data URL (base64) for the screenshot.
        model: Vision-capable model name.
        keys: LLM API keys/config.

    Returns:
        Dict with index and extracted text.
    """
    messages = _build_ocr_messages(image_data_url)
    text = call_llm(
        keys=keys,
        model_name=model,
        messages=messages,
        stream=False
    )
    return {"index": index, "text": text or ""}


@app.route('/ext/ocr', methods=['POST'])
@require_ext_auth
def ext_ocr():
    """
    Perform OCR on a list of screenshots using a vision-capable LLM.

    Request body:
        {
            "images": ["data:image/png;base64,...", ...],
            "url": "https://...",
            "title": "Page title",
            "model": "openai/gpt-4o"   # optional
        }

    Returns:
        {
            "text": "combined OCR text",
            "pages": [{ "index": 0, "text": "..." }, ...]
        }
    """
    if not LLM_AVAILABLE:
        return jsonify({'error': 'LLM service not available'}), 503

    try:
        data = request.get_json() or {}
        images = data.get('images') or []
        model = data.get('model') or OCR_VISION_MODEL

        if not isinstance(images, list) or not images:
            return jsonify({'error': 'images[] is required'}), 400

        if len(images) > OCR_MAX_IMAGES:
            return jsonify({'error': f'Max {OCR_MAX_IMAGES} images allowed'}), 400

        keys = keyParser_for_extension()

        pages: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(OCR_MAX_WORKERS, len(images))) as executor:
            futures = {
                executor.submit(_ocr_single_image, idx, img, model, keys): idx
                for idx, img in enumerate(images)
            }
            for future in as_completed(futures):
                pages.append(future.result())

        pages.sort(key=lambda p: p["index"])
        combined_text = "\n\n--- PAGE ---\n\n".join(p["text"] for p in pages if p.get("text"))

        return jsonify({
            "text": combined_text,
            "pages": pages
        })

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Custom Scripts Endpoints
# =============================================================================

@app.route('/ext/scripts', methods=['GET'])
@require_ext_auth
def ext_list_scripts():
    """
    List user's custom scripts.
    
    Query params:
        enabled_only: Only return enabled scripts (default false)
        script_type: Filter by type ('functional' or 'parsing')
        limit: Maximum number (default 100)
        offset: Pagination offset (default 0)
    
    Returns:
        {"scripts": [...], "total": N}
    """
    try:
        email = request.ext_user_email
        enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'
        script_type = request.args.get('script_type')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        db = get_extension_db()
        scripts = db.get_custom_scripts(
            email,
            enabled_only=enabled_only,
            script_type=script_type,
            limit=limit,
            offset=offset
        )
        
        return jsonify({
            'scripts': scripts,
            'total': len(scripts)
        })
        
    except Exception as e:
        logger.error(f"Error listing scripts: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts', methods=['POST'])
@require_ext_auth
def ext_create_script():
    """
    Create a new custom script.
    
    Request body:
        {
            "name": "LeetCode Helper",
            "description": "Copy problem details",
            "script_type": "functional",
            "match_patterns": ["*://leetcode.com/problems/*"],
            "match_type": "glob",
            "code": "const handlers = { ... }; window.__scriptHandlers = handlers;",
            "actions": [
                {
                    "id": "copy-problem",
                    "name": "Copy Problem",
                    "icon": "clipboard",
                    "exposure": "floating",
                    "handler": "copyProblem"
                }
            ],
            "conversation_id": "optional_conv_id"
        }
    
    Returns:
        {"script": {...}}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        # Validate required fields
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Script name required'}), 400
        
        match_patterns = data.get('match_patterns', [])
        if not match_patterns or not isinstance(match_patterns, list):
            return jsonify({'error': 'At least one match pattern required'}), 400
        
        code = data.get('code', '').strip()
        if not code:
            return jsonify({'error': 'Script code required'}), 400
        
        db = get_extension_db()
        script = db.create_custom_script(
            user_email=email,
            name=name,
            match_patterns=match_patterns,
            code=code,
            description=data.get('description'),
            script_type=data.get('script_type', 'functional'),
            match_type=data.get('match_type', 'glob'),
            actions=data.get('actions'),
            conversation_id=data.get('conversation_id'),
            created_with_llm=data.get('created_with_llm', True)
        )
        
        return jsonify({'script': script})
        
    except Exception as e:
        logger.error(f"Error creating script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/<script_id>', methods=['GET'])
@require_ext_auth
def ext_get_script(script_id):
    """
    Get a specific script by ID.
    
    Args:
        script_id: ID of the script
    
    Returns:
        {"script": {...}}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        script = db.get_custom_script(email, script_id)
        if not script:
            return jsonify({'error': 'Script not found'}), 404
        
        return jsonify({'script': script})
        
    except Exception as e:
        logger.error(f"Error getting script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/<script_id>', methods=['PUT'])
@require_ext_auth
def ext_update_script(script_id):
    """
    Update a custom script.
    
    Request body:
        {"name": "New Name", "code": "...", "actions": [...], ...}
    
    Returns:
        {"script": {...}}
    """
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        db = get_extension_db()
        
        # Verify script exists
        existing = db.get_custom_script(email, script_id)
        if not existing:
            return jsonify({'error': 'Script not found'}), 404
        
        # Update the script
        success = db.update_custom_script(email, script_id, **data)
        
        if success:
            script = db.get_custom_script(email, script_id)
            return jsonify({'script': script})
        else:
            return jsonify({'error': 'Update failed'}), 500
        
    except Exception as e:
        logger.error(f"Error updating script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/<script_id>', methods=['DELETE'])
@require_ext_auth
def ext_delete_script(script_id):
    """
    Delete a custom script.
    
    Args:
        script_id: ID of the script to delete
    
    Returns:
        {"message": "Deleted successfully"}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        success = db.delete_custom_script(email, script_id)
        
        if success:
            return jsonify({'message': 'Deleted successfully'})
        else:
            return jsonify({'error': 'Script not found'}), 404
        
    except Exception as e:
        logger.error(f"Error deleting script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/for-url', methods=['GET'])
@require_ext_auth
def ext_get_scripts_for_url():
    """
    Get all scripts that match a given URL.
    
    Query params:
        url: Full URL to match against (required)
    
    Returns:
        {"scripts": [...]}
    """
    try:
        email = request.ext_user_email
        url = request.args.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL parameter required'}), 400
        
        db = get_extension_db()
        scripts = db.get_scripts_for_url(email, url)
        
        return jsonify({'scripts': scripts})
        
    except Exception as e:
        logger.error(f"Error getting scripts for URL: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/<script_id>/toggle', methods=['POST'])
@require_ext_auth
def ext_toggle_script(script_id):
    """
    Toggle a script's enabled status.
    
    Args:
        script_id: ID of the script
    
    Returns:
        {"script": {...}, "enabled": true/false}
    """
    try:
        email = request.ext_user_email
        db = get_extension_db()
        
        # Get current state
        script = db.get_custom_script(email, script_id)
        if not script:
            return jsonify({'error': 'Script not found'}), 404
        
        # Toggle enabled status
        new_enabled = not script['enabled']
        success = db.update_custom_script(email, script_id, enabled=new_enabled)
        
        if success:
            script = db.get_custom_script(email, script_id)
            return jsonify({'script': script, 'enabled': new_enabled})
        else:
            return jsonify({'error': 'Toggle failed'}), 500
        
    except Exception as e:
        logger.error(f"Error toggling script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/generate', methods=['POST'])
@require_ext_auth
def ext_generate_script():
    """
    Generate a script using LLM based on description and page context.
    
    Request body:
        {
            "description": "Script for LeetCode to copy problem details",
            "page_html": "<html>...",
            "page_url": "https://leetcode.com/problems/two-sum/",
            "conversation_id": "optional",
            "refinement": "Make the button blue"  // Optional, for iterations
        }
    
    Returns:
        {
            "script": {
                "name": "LeetCode Helper",
                "description": "...",
                "match_patterns": ["*://leetcode.com/problems/*"],
                "code": "...",
                "actions": [...]
            },
            "explanation": "I created a script that..."
        }
    """
    if not LLM_AVAILABLE:
        return jsonify({'error': 'LLM service not available'}), 503
    
    try:
        email = request.ext_user_email
        data = request.get_json() or {}
        
        description = data.get('description', '').strip()
        if not description:
            return jsonify({'error': 'Description required'}), 400
        
        page_url = data.get('page_url', '')
        page_html = data.get('page_html', '')
        refinement = data.get('refinement', '')
        
        # Truncate HTML if too long (keep first 50KB)
        if len(page_html) > 50000:
            page_html = page_html[:50000] + "\n<!-- ... truncated ... -->"
        
        # Build the prompt for script generation
        system_prompt = """You are an expert JavaScript developer specializing in browser userscripts (Tampermonkey-style).
Your task is to create custom scripts that augment web pages with useful functionality.

IMPORTANT RUNTIME CONSTRAINTS (follow strictly):
- The script runs in a sandboxed environment with **NO direct access to the page DOM**.
- Do NOT use `document`, `window.document`, `querySelector`, or any direct DOM access.
- Do NOT use `eval`, `new Function`, dynamic imports, or external libraries.
- To interact with the page, you MUST use the provided `aiAssistant.dom.*` functions (they execute in the content script).
- Keep scripts deterministic and safe: avoid infinite loops; keep operations small and targeted.

NOTE ABOUT `query/queryAll`:
- Do NOT rely on getting a live Element back from `aiAssistant.dom.query()` / `queryAll()`.
- Prefer `exists()`, `count()`, and action methods like `click()`, `setValue()`, `type()`, `hide()`, `remove()`, etc.

SCRIPT SHAPE REQUIREMENTS:
- Always create a handlers object: `const handlers = { ... }`
- Always export it: `window.__scriptHandlers = handlers;`
- Every action definition's `handler` field must match a function name in `handlers`.

The scripts you create will have access to an `aiAssistant` API with these methods:
- aiAssistant.dom.query(selector) - Returns first matching element
- aiAssistant.dom.queryAll(selector) - Returns array of matching elements
- aiAssistant.dom.exists(selector) - Returns true/false if element exists
- aiAssistant.dom.count(selector) - Returns number of matching elements
- aiAssistant.dom.getText(selector) - Gets text content
- aiAssistant.dom.getHtml(selector) - Gets innerHTML
- aiAssistant.dom.getAttr(selector, name) - Gets attribute value
- aiAssistant.dom.setAttr(selector, name, value) - Sets attribute value
- aiAssistant.dom.getValue(selector) - Gets value for inputs/textareas/selects
- aiAssistant.dom.waitFor(selector, timeout) - Waits for element to appear
- aiAssistant.dom.hide(selector) - Hides element(s)
- aiAssistant.dom.show(selector) - Shows element(s)
- aiAssistant.dom.setHtml(selector, html) - Sets innerHTML
- aiAssistant.dom.scrollIntoView(selector, behavior) - Scroll element into view
- aiAssistant.dom.focus(selector) - Focus element
- aiAssistant.dom.blur(selector) - Blur element
- aiAssistant.dom.click(selector) - Click element
- aiAssistant.dom.setValue(selector, value) - Set value + dispatch input/change
- aiAssistant.dom.type(selector, text, opts) - Type into element (opts: delayMs, clearFirst)
- aiAssistant.dom.remove(selector) - Remove matching elements (useful for ads)
- aiAssistant.dom.addClass(selector, className) - Add class to matching
- aiAssistant.dom.removeClass(selector, className) - Remove class from matching
- aiAssistant.dom.toggleClass(selector, className, force?) - Toggle class on matching
- aiAssistant.clipboard.copy(text) - Copies text to clipboard
- aiAssistant.clipboard.copyHtml(html) - Copies rich text
- aiAssistant.ui.showToast(message, type) - Shows notification ('success', 'error', 'info')
- aiAssistant.ui.showModal(title, content) - Shows modal dialog
- aiAssistant.ui.closeModal() - Closes modal
- aiAssistant.llm.ask(prompt) - Asks LLM a question, returns Promise<string>
- aiAssistant.storage.get(key) - Gets stored value
- aiAssistant.storage.set(key, value) - Stores value

Your script MUST:
1. Define handler functions as an object
2. Export handlers via: window.__scriptHandlers = handlers;
3. Each handler function should be a method that performs one action

Output your response as JSON with this structure:
{
  "name": "Script Name",
  "description": "What the script does",
  "match_patterns": ["*://example.com/*"],
  "script_type": "functional",
  "code": "const handlers = { actionName() { ... } }; window.__scriptHandlers = handlers;",
  "actions": [
    {
      "id": "action-id",
      "name": "Action Display Name",
      "description": "What this action does",
      "icon": "clipboard|copy|download|eye|trash|star|edit|settings|search|refresh",
      "exposure": "floating",
      "handler": "actionName"
    }
  ],
  "explanation": "Explanation of what the script does and how to use it"
}

Only output the JSON, no markdown code blocks."""

        user_prompt = f"""Create a userscript based on this request:

**Description:** {description}
"""
        
        if refinement:
            user_prompt += f"\n**Refinement/Additional requirements:** {refinement}\n"
        
        if page_url:
            user_prompt += f"\n**Target URL:** {page_url}\n"
        
        if page_html:
            user_prompt += f"\n**Page HTML (for understanding structure):**\n```html\n{page_html}\n```\n"
        
        user_prompt += "\nGenerate the script JSON now:"
        
        keys = keyParser_for_extension()
        
        # Call LLM
        response = call_llm(
            keys=keys,
            model_name=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=False
        )
        
        # Parse the JSON response
        try:
            # Try to extract JSON from the response
            response_text = response.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
            
            script_data = json.loads(response_text)
            
            # Extract explanation separately
            explanation = script_data.pop('explanation', 'Script generated successfully.')
            
            return jsonify({
                'script': script_data,
                'explanation': explanation
            })
            
        except json.JSONDecodeError as e:
            # If JSON parsing fails, return the raw response with error
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return jsonify({
                'error': 'Failed to parse generated script',
                'raw_response': response,
                'parse_error': str(e)
            }), 500
        
    except Exception as e:
        logger.error(f"Error generating script: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/ext/scripts/validate', methods=['POST'])
@require_ext_auth
def ext_validate_script():
    """
    Validate script code syntax.
    
    Request body:
        {"code": "const handlers = { ... };"}
    
    Returns:
        {"valid": true} or {"valid": false, "error": "Syntax error at line..."}
    """
    try:
        data = request.get_json() or {}
        code = data.get('code', '')
        
        if not code:
            return jsonify({'valid': False, 'error': 'No code provided'})
        
        # Basic JavaScript syntax validation
        # We check for common errors but can't fully validate JS on server
        # Real validation happens in browser
        
        # Check for balanced braces/brackets/parens
        stack = []
        pairs = {')': '(', ']': '[', '}': '{'}
        
        in_string = False
        string_char = None
        escaped = False
        
        for i, char in enumerate(code):
            if escaped:
                escaped = False
                continue
            
            if char == '\\':
                escaped = True
                continue
            
            if in_string:
                if char == string_char:
                    in_string = False
                continue
            
            if char in '"\'`':
                in_string = True
                string_char = char
                continue
            
            if char in '([{':
                stack.append(char)
            elif char in ')]}':
                if not stack or stack[-1] != pairs[char]:
                    return jsonify({
                        'valid': False,
                        'error': f'Unmatched {char} at position {i}'
                    })
                stack.pop()
        
        if stack:
            return jsonify({
                'valid': False,
                'error': f'Unclosed {stack[-1]}'
            })
        
        if in_string:
            return jsonify({
                'valid': False,
                'error': 'Unclosed string'
            })
        
        return jsonify({'valid': True})
        
    except Exception as e:
        logger.error(f"Error validating script: {e}")
        return jsonify({'valid': False, 'error': str(e)})


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

