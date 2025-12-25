"""
Integration Tests for Extension Server API

This script tests all API endpoints in extension_server.py using the requests library.
It covers authentication, conversations, chat, prompts, memories, and settings.

Usage:
    # Run with pytest
    pytest test_extension_api.py -v
    
    # Or run directly
    python test_extension_api.py
    
Environment Variables:
    TEST_EMAIL: Test user email (default: test@example.com)
    TEST_PASSWORD: Test user password (default: uses PASSWORD env var or XXXX)
    EXT_SERVER_URL: Extension server URL (default: http://localhost:5001)
"""

import os
import sys
import json
import time
import unittest
import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class Config:
    """Test configuration loaded from environment."""
    base_url: str = os.getenv("EXT_SERVER_URL", "http://localhost:5001")
    email: str = os.getenv("TEST_EMAIL", "test@example.com")
    password: str = os.getenv("TEST_PASSWORD", os.getenv("PASSWORD", "XXXX"))
    timeout: int = 30
    
    def __post_init__(self):
        self.base_url = self.base_url.rstrip('/')


CONFIG = Config()


# =============================================================================
# Test Client Helper
# =============================================================================

class ExtensionAPIClient:
    """Helper class for making API requests to extension server."""
    
    def __init__(self, base_url: str = CONFIG.base_url):
        self.base_url = base_url
        self.token: Optional[str] = None
        self.session = requests.Session()
        
    @property
    def headers(self) -> Dict[str, str]:
        """Get headers with auth token if available."""
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h
    
    def _url(self, path: str) -> str:
        """Build full URL for endpoint."""
        return f"{self.base_url}{path}"
    
    def get(self, path: str, params: Dict = None) -> requests.Response:
        """Make GET request."""
        return self.session.get(
            self._url(path), 
            params=params, 
            headers=self.headers,
            timeout=CONFIG.timeout
        )
    
    def post(self, path: str, data: Dict = None) -> requests.Response:
        """Make POST request."""
        return self.session.post(
            self._url(path), 
            json=data, 
            headers=self.headers,
            timeout=CONFIG.timeout
        )
    
    def put(self, path: str, data: Dict = None) -> requests.Response:
        """Make PUT request."""
        return self.session.put(
            self._url(path), 
            json=data, 
            headers=self.headers,
            timeout=CONFIG.timeout
        )
    
    def delete(self, path: str) -> requests.Response:
        """Make DELETE request."""
        return self.session.delete(
            self._url(path), 
            headers=self.headers,
            timeout=CONFIG.timeout
        )
    
    def login(self, email: str = CONFIG.email, password: str = CONFIG.password) -> Dict:
        """Login and store token."""
        resp = self.post("/ext/auth/login", {"email": email, "password": password})
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("token")
            return data
        resp.raise_for_status()
    
    def logout(self):
        """Logout and clear token."""
        if self.token:
            self.post("/ext/auth/logout")
            self.token = None


# =============================================================================
# Test Classes
# =============================================================================

class TestHealthEndpoint(unittest.TestCase):
    """Test /ext/health endpoint (no auth required)."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
    
    def test_health_check(self):
        """Health endpoint should return status without auth."""
        resp = self.client.get("/ext/health")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("services", data)
        self.assertIn("timestamp", data)
        
    def test_health_services_status(self):
        """Health should report service availability."""
        resp = self.client.get("/ext/health")
        data = resp.json()
        
        services = data["services"]
        self.assertIn("prompt_lib", services)
        self.assertIn("pkb", services)
        self.assertIn("llm", services)


class TestAuthentication(unittest.TestCase):
    """Test authentication endpoints."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
    
    def test_login_success(self):
        """Should login with valid credentials."""
        resp = self.client.post("/ext/auth/login", {
            "email": CONFIG.email,
            "password": CONFIG.password
        })
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("token", data)
        self.assertEqual(data["email"], CONFIG.email)
        self.assertIsNotNone(data.get("token"))
        
    def test_login_missing_fields(self):
        """Should reject login with missing fields."""
        # Missing password
        resp = self.client.post("/ext/auth/login", {"email": CONFIG.email})
        self.assertEqual(resp.status_code, 400)
        
        # Missing email
        resp = self.client.post("/ext/auth/login", {"password": "test"})
        self.assertEqual(resp.status_code, 400)
        
        # Empty body
        resp = self.client.post("/ext/auth/login", {})
        self.assertEqual(resp.status_code, 400)
    
    def test_login_invalid_credentials(self):
        """Should reject invalid credentials."""
        resp = self.client.post("/ext/auth/login", {
            "email": CONFIG.email,
            "password": "wrong_password_12345"
        })
        self.assertEqual(resp.status_code, 401)
    
    def test_verify_token_valid(self):
        """Should verify valid token."""
        self.client.login()
        
        resp = self.client.post("/ext/auth/verify")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["email"], CONFIG.email)
    
    def test_verify_token_invalid(self):
        """Should reject invalid token."""
        self.client.token = "invalid_token_here"
        
        resp = self.client.post("/ext/auth/verify")
        self.assertEqual(resp.status_code, 200)  # Returns 200 with valid=false
        
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertIn("error", data)
    
    def test_verify_token_missing(self):
        """Should handle missing token."""
        resp = self.client.post("/ext/auth/verify")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertFalse(data["valid"])
    
    def test_logout(self):
        """Should logout successfully."""
        self.client.login()
        
        resp = self.client.post("/ext/auth/logout")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("message", data)
    
    def test_protected_endpoint_without_auth(self):
        """Protected endpoints should reject requests without auth."""
        resp = self.client.get("/ext/conversations")
        self.assertEqual(resp.status_code, 401)


class TestPrompts(unittest.TestCase):
    """Test prompt endpoints (read-only)."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
    
    def tearDown(self):
        self.client.logout()
    
    def test_list_prompts(self):
        """Should list available prompts."""
        resp = self.client.get("/ext/prompts")
        
        # May return 503 if prompt lib not available
        if resp.status_code == 503:
            self.skipTest("Prompt library not available")
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("prompts", data)
        self.assertIsInstance(data["prompts"], list)
    
    def test_get_prompt_by_name(self):
        """Should get specific prompt by name."""
        # First list prompts to get a valid name
        list_resp = self.client.get("/ext/prompts")
        if list_resp.status_code == 503:
            self.skipTest("Prompt library not available")
        
        prompts = list_resp.json().get("prompts", [])
        if not prompts:
            self.skipTest("No prompts available")
        
        prompt_name = prompts[0]["name"]
        resp = self.client.get(f"/ext/prompts/{prompt_name}")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertEqual(data["name"], prompt_name)
        self.assertIn("content", data)
    
    def test_get_prompt_not_found(self):
        """Should return 404 for non-existent prompt."""
        resp = self.client.get("/ext/prompts/nonexistent_prompt_xyz")
        
        if resp.status_code == 503:
            self.skipTest("Prompt library not available")
        
        self.assertEqual(resp.status_code, 404)


class TestMemories(unittest.TestCase):
    """Test memory/PKB endpoints (read-only)."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
    
    def tearDown(self):
        self.client.logout()
    
    def test_list_memories(self):
        """Should list memories."""
        resp = self.client.get("/ext/memories")
        
        if resp.status_code == 503:
            self.skipTest("PKB not available")
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("memories", data)
        self.assertIn("total", data)
    
    def test_list_memories_with_pagination(self):
        """Should support pagination."""
        resp = self.client.get("/ext/memories", params={"limit": 5, "offset": 0})
        
        if resp.status_code == 503:
            self.skipTest("PKB not available")
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data["memories"]), 5)
    
    def test_search_memories(self):
        """Should search memories."""
        resp = self.client.post("/ext/memories/search", {
            "query": "test query",
            "k": 5
        })
        
        if resp.status_code == 503:
            self.skipTest("PKB not available")
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
    
    def test_search_memories_missing_query(self):
        """Should reject search without query."""
        resp = self.client.post("/ext/memories/search", {})
        
        if resp.status_code == 503:
            self.skipTest("PKB not available")
        
        self.assertEqual(resp.status_code, 400)
    
    def test_get_pinned_memories(self):
        """Should get pinned memories."""
        resp = self.client.get("/ext/memories/pinned")
        
        if resp.status_code == 503:
            self.skipTest("PKB not available")
        
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("memories", data)


class TestConversations(unittest.TestCase):
    """Test conversation CRUD operations."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
        self.created_conv_ids = []
    
    def tearDown(self):
        # Cleanup created conversations
        for conv_id in self.created_conv_ids:
            try:
                self.client.delete(f"/ext/conversations/{conv_id}")
            except:
                pass
        self.client.logout()
    
    def _create_conversation(self, **kwargs) -> Dict:
        """Helper to create conversation and track for cleanup."""
        defaults = {
            "title": f"Test Conv {time.time()}",
            "is_temporary": True,
            "model": "openai/gpt-4o-mini"
        }
        defaults.update(kwargs)
        
        resp = self.client.post("/ext/conversations", defaults)
        self.assertEqual(resp.status_code, 200)
        
        conv = resp.json()["conversation"]
        self.created_conv_ids.append(conv["conversation_id"])
        return conv
    
    def test_create_conversation(self):
        """Should create a new conversation."""
        resp = self.client.post("/ext/conversations", {
            "title": "Test Conversation",
            "is_temporary": True,
            "model": "openai/gpt-4o-mini",
            "prompt_name": "Short",
            "history_length": 10
        })
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("conversation", data)
        conv = data["conversation"]
        
        self.assertIn("conversation_id", conv)
        self.assertEqual(conv["title"], "Test Conversation")
        self.assertTrue(conv["is_temporary"])
        
        self.created_conv_ids.append(conv["conversation_id"])
    
    def test_create_conversation_defaults(self):
        """Should use defaults for optional fields."""
        resp = self.client.post("/ext/conversations", {})
        self.assertEqual(resp.status_code, 200)
        
        conv = resp.json()["conversation"]
        self.assertEqual(conv["title"], "New Chat")
        self.assertTrue(conv["is_temporary"])
        
        self.created_conv_ids.append(conv["conversation_id"])
    
    def test_list_conversations(self):
        """Should list user's conversations."""
        # Create a conversation first
        self._create_conversation(title="List Test")
        
        resp = self.client.get("/ext/conversations")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("conversations", data)
        self.assertIn("total", data)
        self.assertGreater(len(data["conversations"]), 0)
    
    def test_list_conversations_pagination(self):
        """Should support pagination."""
        # Create multiple conversations
        for i in range(3):
            self._create_conversation(title=f"Pagination Test {i}")
        
        resp = self.client.get("/ext/conversations", params={"limit": 2})
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertLessEqual(len(data["conversations"]), 2)
    
    def test_get_conversation(self):
        """Should get conversation with messages."""
        conv = self._create_conversation(title="Get Test")
        
        resp = self.client.get(f"/ext/conversations/{conv['conversation_id']}")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("conversation", data)
        self.assertEqual(data["conversation"]["conversation_id"], conv["conversation_id"])
        self.assertIn("messages", data["conversation"])
    
    def test_get_conversation_not_found(self):
        """Should return 404 for non-existent conversation."""
        resp = self.client.get("/ext/conversations/nonexistent-conv-id")
        self.assertEqual(resp.status_code, 404)
    
    def test_update_conversation(self):
        """Should update conversation metadata."""
        conv = self._create_conversation(title="Original Title")
        
        resp = self.client.put(f"/ext/conversations/{conv['conversation_id']}", {
            "title": "Updated Title",
            "is_temporary": False
        })
        self.assertEqual(resp.status_code, 200)
        
        updated = resp.json()["conversation"]
        self.assertEqual(updated["title"], "Updated Title")
        self.assertFalse(updated["is_temporary"])
    
    def test_delete_conversation(self):
        """Should delete conversation."""
        conv = self._create_conversation(title="Delete Test")
        conv_id = conv["conversation_id"]
        
        # Remove from cleanup list since we're testing deletion
        self.created_conv_ids.remove(conv_id)
        
        resp = self.client.delete(f"/ext/conversations/{conv_id}")
        self.assertEqual(resp.status_code, 200)
        
        # Verify it's deleted
        resp = self.client.get(f"/ext/conversations/{conv_id}")
        self.assertEqual(resp.status_code, 404)


class TestChat(unittest.TestCase):
    """Test chat/messaging functionality."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
        self.created_conv_ids = []
    
    def tearDown(self):
        for conv_id in self.created_conv_ids:
            try:
                self.client.delete(f"/ext/conversations/{conv_id}")
            except:
                pass
        self.client.logout()
    
    def _create_conversation(self) -> str:
        """Helper to create conversation."""
        resp = self.client.post("/ext/conversations", {
            "title": f"Chat Test {time.time()}",
            "is_temporary": True
        })
        conv_id = resp.json()["conversation"]["conversation_id"]
        self.created_conv_ids.append(conv_id)
        return conv_id
    
    def test_add_message_without_llm(self):
        """Should add message without triggering LLM."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "This is a test message"
        })
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("message", data)
        self.assertEqual(data["message"]["role"], "user")
        self.assertEqual(data["message"]["content"], "This is a test message")
    
    def test_add_message_with_page_context(self):
        """Should add message with page context."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "Summarize this page",
            "page_context": {
                "url": "https://example.com",
                "title": "Example Page",
                "content": "Some page content here..."
            }
        })
        self.assertEqual(resp.status_code, 200)
    
    def test_add_message_invalid_role(self):
        """Should reject invalid message role."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "invalid_role",
            "content": "Test"
        })
        self.assertEqual(resp.status_code, 400)
    
    def test_add_message_empty_content(self):
        """Should reject empty message content."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": ""
        })
        self.assertEqual(resp.status_code, 400)
    
    def test_delete_message(self):
        """Should delete a message."""
        conv_id = self._create_conversation()
        
        # Add a message
        add_resp = self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "Message to delete"
        })
        msg_id = add_resp.json()["message"]["message_id"]
        
        # Delete it
        del_resp = self.client.delete(f"/ext/chat/{conv_id}/messages/{msg_id}")
        self.assertEqual(del_resp.status_code, 200)
        
        # Verify it's gone
        conv_resp = self.client.get(f"/ext/conversations/{conv_id}")
        messages = conv_resp.json()["conversation"]["messages"]
        msg_ids = [m["message_id"] for m in messages]
        self.assertNotIn(msg_id, msg_ids)
    
    def test_chat_non_streaming(self):
        """Should send message and get LLM response (non-streaming)."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}", {
            "message": "Say 'hello world' and nothing else",
            "stream": False
        })
        
        if resp.status_code == 503:
            self.skipTest("LLM service not available")
        
        if resp.status_code == 500:
            # Check if it's an API key error - skip the test in that case
            error_msg = resp.json().get('error', '')
            if 'api_key' in error_msg.lower() or 'openai_api_key' in error_msg.lower() or 'openrouter' in error_msg.lower():
                self.skipTest(f"LLM API keys not configured: {error_msg}")
            # Otherwise fail the test
            self.fail(f"LLM call failed: {error_msg}")
        
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("response", data)
        self.assertIn("message_id", data)
        self.assertIn("user_message_id", data)
        self.assertIsInstance(data["response"], str)
        self.assertGreater(len(data["response"]), 0)
    
    def test_chat_missing_message(self):
        """Should reject chat without message."""
        conv_id = self._create_conversation()
        
        resp = self.client.post(f"/ext/chat/{conv_id}", {})
        self.assertEqual(resp.status_code, 400)
    
    def test_chat_conversation_not_found(self):
        """Should return 404 for non-existent conversation."""
        resp = self.client.post("/ext/chat/nonexistent-conv-id", {
            "message": "Hello"
        })
        self.assertEqual(resp.status_code, 404)


class TestMultiTurnConversation(unittest.TestCase):
    """Test multi-turn conversation flows."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
        self.created_conv_ids = []
    
    def tearDown(self):
        for conv_id in self.created_conv_ids:
            try:
                self.client.delete(f"/ext/conversations/{conv_id}")
            except:
                pass
        self.client.logout()
    
    def test_multi_turn_message_flow(self):
        """Should maintain conversation history across turns."""
        # Create conversation
        resp = self.client.post("/ext/conversations", {
            "title": "Multi-turn Test"
        })
        conv_id = resp.json()["conversation"]["conversation_id"]
        self.created_conv_ids.append(conv_id)
        
        # Add first message
        self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "My name is TestUser"
        })
        
        # Add assistant response
        self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "assistant",
            "content": "Hello TestUser! Nice to meet you."
        })
        
        # Add follow-up
        self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "What is my name?"
        })
        
        # Check conversation has all messages
        resp = self.client.get(f"/ext/conversations/{conv_id}")
        messages = resp.json()["conversation"]["messages"]
        
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[2]["role"], "user")
    
    def test_conversation_history_in_llm_call(self):
        """Should include history when calling LLM."""
        resp = self.client.post("/ext/conversations", {
            "title": "History Test",
            "history_length": 5
        })
        conv_id = resp.json()["conversation"]["conversation_id"]
        self.created_conv_ids.append(conv_id)
        
        # Add context message
        self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "user",
            "content": "Remember this secret code: ALPHA123"
        })
        self.client.post(f"/ext/chat/{conv_id}/message", {
            "role": "assistant",
            "content": "I'll remember that the secret code is ALPHA123."
        })
        
        # Ask about the code - LLM should have context
        resp = self.client.post(f"/ext/chat/{conv_id}", {
            "message": "What was the secret code?",
            "stream": False
        })
        
        if resp.status_code == 503:
            self.skipTest("LLM service not available")
        
        if resp.status_code == 500:
            error_msg = resp.json().get('error', '')
            if 'api_key' in error_msg.lower() or 'openai_api_key' in error_msg.lower() or 'openrouter' in error_msg.lower():
                self.skipTest(f"LLM API keys not configured: {error_msg}")
            self.fail(f"LLM call failed: {error_msg}")
        
        self.assertEqual(resp.status_code, 200)
        response = resp.json()["response"].lower()
        # The response should contain the code
        self.assertIn("alpha123", response)


class TestSettings(unittest.TestCase):
    """Test settings endpoints."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
    
    def tearDown(self):
        self.client.logout()
    
    def test_get_settings(self):
        """Should get user settings."""
        resp = self.client.get("/ext/settings")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("settings", data)
    
    def test_update_settings(self):
        """Should update user settings."""
        resp = self.client.put("/ext/settings", {
            "default_model": "anthropic/claude-3.5-sonnet",
            "history_length": 20
        })
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("settings", data)
        
        # Verify settings were saved
        get_resp = self.client.get("/ext/settings")
        settings = get_resp.json()["settings"]
        self.assertEqual(settings.get("default_model"), "anthropic/claude-3.5-sonnet")


class TestModels(unittest.TestCase):
    """Test models endpoint."""
    
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
    
    def tearDown(self):
        self.client.logout()
    
    def test_list_models(self):
        """Should list available models."""
        resp = self.client.get("/ext/models")
        self.assertEqual(resp.status_code, 200)
        
        data = resp.json()
        self.assertIn("models", data)
        self.assertIsInstance(data["models"], list)
        self.assertGreater(len(data["models"]), 0)
        
        # Check model structure
        model = data["models"][0]
        self.assertIn("id", model)
        self.assertIn("name", model)
        self.assertIn("provider", model)


# =============================================================================
# Test Runner
# =============================================================================

class ResultTracker:
    """Simple test result tracker."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []
    
    def add_pass(self, name: str):
        self.passed += 1
        print(f"  ✓ {name}")
    
    def add_fail(self, name: str, error: str):
        self.failed += 1
        self.errors.append((name, error))
        print(f"  ✗ {name}: {error}")
    
    def add_skip(self, name: str, reason: str):
        self.skipped += 1
        print(f"  ○ {name}: SKIPPED ({reason})")
    
    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*60}")
        print(f"Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped out of {total} tests")
        if self.errors:
            print(f"\nFailed tests:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


def run_tests():
    """Run all tests and report results."""
    print(f"Extension Server API Integration Tests")
    print(f"Server: {CONFIG.base_url}")
    print(f"User: {CONFIG.email}")
    print("=" * 60)
    
    # Check server is running
    try:
        resp = requests.get(f"{CONFIG.base_url}/ext/health", timeout=5)
        if resp.status_code != 200:
            print(f"ERROR: Server health check failed with status {resp.status_code}")
            return False
        print(f"Server is healthy: {resp.json()}")
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to server at {CONFIG.base_url}")
        print("Make sure the extension server is running:")
        print("  python extension_server.py --port 5001 --debug")
        return False
    except Exception as e:
        print(f"ERROR: Health check failed: {e}")
        return False
    
    print()
    
    # Run tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        TestHealthEndpoint,
        TestAuthentication,
        TestPrompts,
        TestMemories,
        TestConversations,
        TestChat,
        TestMultiTurnConversation,
        TestSettings,
        TestModels,
    ]
    
    for test_class in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)

