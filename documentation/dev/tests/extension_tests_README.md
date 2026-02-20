# Extension Server Integration Tests

> **⚠️ DEPRECATED**: These tests targeted the deprecated `extension_server.py` (port 5001). The test files in `extension/tests/` have been deleted as part of M7 cleanup. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture. New integration tests should target the main server endpoints (`/ext/*` routes in `endpoints/ext_*.py`).

This directory contained integration tests for the Extension Server API.

## Quick Start

### Option 1: Auto-start Server (Recommended)

```bash
# Make the script executable
chmod +x run_tests.sh

# Run tests (starts server automatically)
./run_tests.sh
```

Or using Python:
```bash
python run_integration_tests.py
```

### Option 2: Manual Server + Tests

Terminal 1 - Start server:
```bash
cd /path/to/chatgpt-iterative
conda activate science-reader
python extension_server.py --port 5001 --debug
```

Terminal 2 - Run tests:
```bash
cd /path/to/chatgpt-iterative
conda activate science-reader

# With pytest
pytest extension/tests/test_extension_api.py -v

# Or directly
python extension/tests/test_extension_api.py
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EXT_SERVER_URL` | `http://localhost:5001` | Server URL |
| `TEST_EMAIL` | `test@example.com` | Test user email |
| `TEST_PASSWORD` | `XXXX` (or `PASSWORD` env) | Test user password |
| `PASSWORD` | `XXXX` | Fallback password |

### Command Line Options

**run_integration_tests.py:**
```
--port PORT         Server port (default: 5001)
--email EMAIL       Test user email
--password PASS     Test user password
--no-server         Don't start server, use existing one
--url URL           Server URL (with --no-server)
-v, --verbose       Verbose output
```

**run_tests.sh:**
```
--port PORT         Server port
--email EMAIL       Test user email
--password PASS     Test user password
--no-server         Use existing server
-v                  Verbose output
```

## Test Coverage

### Authentication Tests
- ✅ Login with valid credentials
- ✅ Login with invalid credentials
- ✅ Login with missing fields
- ✅ Token verification (valid/invalid)
- ✅ Logout
- ✅ Protected endpoint without auth

### Prompt Tests (Read-Only)
- ✅ List prompts
- ✅ Get prompt by name
- ✅ Get non-existent prompt (404)

### Memory/PKB Tests (Read-Only)
- ✅ List memories
- ✅ List with pagination
- ✅ Search memories
- ✅ Get pinned memories

### Conversation Tests
- ✅ Create conversation
- ✅ Create with defaults
- ✅ List conversations
- ✅ List with pagination
- ✅ Get conversation
- ✅ Get non-existent (404)
- ✅ Update conversation
- ✅ Delete conversation

### Chat Tests
- ✅ Add message without LLM
- ✅ Add message with page context
- ✅ Invalid role rejection
- ✅ Empty content rejection
- ✅ Delete message
- ✅ Non-streaming LLM response
- ✅ Missing message rejection
- ✅ Non-existent conversation (404)

### Multi-Turn Conversation Tests
- ✅ Conversation history maintained
- ✅ History included in LLM calls

### Settings Tests
- ✅ Get settings
- ✅ Update settings

### Utility Tests
- ✅ List models
- ✅ Health check

## Troubleshooting

### "Cannot connect to server"
Make sure the extension server is running:
```bash
python extension_server.py --port 5001 --debug
```

### "Invalid credentials"
Set the correct password:
```bash
export PASSWORD="your_password"
./run_tests.sh
```

### "LLM service not available"
LLM tests are skipped if `OPENROUTER_API_KEY` is not set.

### "PKB not available"
Memory tests are skipped if the PKB database is not initialized.

## Adding New Tests

1. Add test methods to existing test classes in `test_extension_api.py`
2. Follow the naming convention: `test_<feature>_<scenario>`
3. Use `self.skipTest("reason")` for conditional skipping
4. Clean up created resources in `tearDown()`

Example:
```python
class TestMyFeature(unittest.TestCase):
    def setUp(self):
        self.client = ExtensionAPIClient()
        self.client.login()
    
    def tearDown(self):
        self.client.logout()
    
    def test_my_feature_success(self):
        resp = self.client.get("/ext/my-endpoint")
        self.assertEqual(resp.status_code, 200)
    
    def test_my_feature_error(self):
        resp = self.client.get("/ext/my-endpoint/invalid")
        self.assertEqual(resp.status_code, 404)
```

