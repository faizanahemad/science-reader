"""
Extension Server Integration Tests

This package contains integration tests for the extension_server.py API.

Test Modules:
    test_extension_api.py - Main integration tests for all API endpoints

Runner Scripts:
    run_integration_tests.py - Python runner that starts server and runs tests
    run_tests.sh - Bash runner with conda activation

Usage:
    # Using pytest
    pytest extension/tests/test_extension_api.py -v
    
    # Using the runner (auto-starts server)
    python extension/tests/run_integration_tests.py
    
    # Using bash script
    ./extension/tests/run_tests.sh
"""

