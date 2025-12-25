#!/usr/bin/env python3
"""
Integration Test Runner for Extension Server

This script:
1. Starts the extension server in a background process
2. Waits for the server to be ready
3. Runs all integration tests
4. Shuts down the server
5. Reports results

Usage:
    # Run with default settings
    python run_integration_tests.py
    
    # Run with custom settings
    python run_integration_tests.py --port 5002 --email test@example.com
    
    # Run with existing server (don't start a new one)
    python run_integration_tests.py --no-server
    
    # Run with verbose output
    python run_integration_tests.py -v

Environment Variables:
    PASSWORD: User password for testing (default: XXXX)
    OPENROUTER_API_KEY: Required for LLM tests
"""

import os
import sys
import time
import signal
import argparse
import subprocess
import requests
from pathlib import Path


# =============================================================================
# Configuration
# =============================================================================

# Get the project root directory
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
EXTENSION_SERVER = PROJECT_ROOT / "extension_server.py"

DEFAULT_PORT = 5001
DEFAULT_HOST = "localhost"
DEFAULT_EMAIL = "test@example.com"
DEFAULT_PASSWORD = os.getenv("PASSWORD", "XXXX")

# How long to wait for server to start
SERVER_STARTUP_TIMEOUT = 30
# How long to wait between health checks
HEALTH_CHECK_INTERVAL = 0.5


# =============================================================================
# Server Management
# =============================================================================

class ServerManager:
    """Manages the extension server process."""
    
    def __init__(self, port: int, host: str = "0.0.0.0", debug: bool = False):
        self.port = port
        self.host = host
        self.debug = debug
        self.process = None
        self.base_url = f"http://localhost:{port}"
    
    def start(self) -> bool:
        """Start the server and wait for it to be ready."""
        if self.is_running():
            print(f"Server already running at {self.base_url}")
            return True
        
        print(f"Starting extension server on port {self.port}...")
        
        # Build command
        cmd = [
            sys.executable,
            str(EXTENSION_SERVER),
            "--port", str(self.port),
            "--host", self.host,
        ]
        if self.debug:
            cmd.append("--debug")
        
        # Set environment
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Start process
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1
            )
        except Exception as e:
            print(f"Failed to start server: {e}")
            return False
        
        # Wait for server to be ready
        print(f"Waiting for server to be ready (timeout: {SERVER_STARTUP_TIMEOUT}s)...")
        start_time = time.time()
        
        while time.time() - start_time < SERVER_STARTUP_TIMEOUT:
            if self.process.poll() is not None:
                # Process exited
                output = self.process.stdout.read()
                print(f"Server exited unexpectedly with code {self.process.returncode}")
                print(f"Output: {output}")
                return False
            
            if self.is_running():
                elapsed = time.time() - start_time
                print(f"Server ready after {elapsed:.1f}s")
                return True
            
            time.sleep(HEALTH_CHECK_INTERVAL)
        
        # Timeout
        print(f"Server failed to start within {SERVER_STARTUP_TIMEOUT}s")
        self.stop()
        return False
    
    def stop(self):
        """Stop the server process."""
        if self.process is None:
            return
        
        print("Stopping server...")
        
        # Try graceful shutdown first
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill
            print("Force killing server...")
            self.process.kill()
            self.process.wait()
        
        self.process = None
        print("Server stopped")
    
    def is_running(self) -> bool:
        """Check if server is responding to health checks."""
        try:
            resp = requests.get(
                f"{self.base_url}/ext/health",
                timeout=2
            )
            return resp.status_code == 200
        except:
            return False


# =============================================================================
# Test Runner
# =============================================================================

def run_tests(base_url: str, email: str, password: str, verbose: bool = False) -> bool:
    """Run the integration tests."""
    print("\n" + "=" * 60)
    print("Running Integration Tests")
    print("=" * 60 + "\n")
    
    # Set environment for tests
    env = os.environ.copy()
    env["EXT_SERVER_URL"] = base_url
    env["TEST_EMAIL"] = email
    env["TEST_PASSWORD"] = password
    
    # Run pytest if available, otherwise run the test script directly
    test_script = SCRIPT_DIR / "test_extension_api.py"
    
    try:
        # Try pytest first
        cmd = [
            sys.executable, "-m", "pytest",
            str(test_script),
            "-v" if verbose else "-q",
            "--tb=short",
            "-x",  # Stop on first failure
        ]
        result = subprocess.run(
            cmd,
            env=env,
            cwd=str(PROJECT_ROOT)
        )
        return result.returncode == 0
        
    except FileNotFoundError:
        # Pytest not installed, run directly
        print("pytest not found, running tests directly...")
        cmd = [sys.executable, str(test_script)]
        result = subprocess.run(
            cmd,
            env=env,
            cwd=str(PROJECT_ROOT)
        )
        return result.returncode == 0


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run extension server integration tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with default settings
    python run_integration_tests.py
    
    # Run against existing server
    python run_integration_tests.py --no-server --url http://localhost:5001
    
    # Run with custom credentials
    python run_integration_tests.py --email user@example.com --password mypass
"""
    )
    
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to run server on (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"Host to bind server to (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--email", default=DEFAULT_EMAIL,
        help=f"Test user email (default: {DEFAULT_EMAIL})"
    )
    parser.add_argument(
        "--password", default=DEFAULT_PASSWORD,
        help="Test user password (default: from PASSWORD env var)"
    )
    parser.add_argument(
        "--url", 
        help="Server URL (only used with --no-server)"
    )
    parser.add_argument(
        "--no-server", action="store_true",
        help="Don't start a server, use existing one"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Run server in debug mode"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose test output"
    )
    
    args = parser.parse_args()
    
    # Determine server URL
    if args.no_server:
        base_url = args.url or f"http://localhost:{args.port}"
        print(f"Using existing server at {base_url}")
        
        # Verify server is running
        try:
            resp = requests.get(f"{base_url}/ext/health", timeout=5)
            if resp.status_code != 200:
                print(f"ERROR: Server health check failed")
                return 1
            print(f"Server is healthy")
        except Exception as e:
            print(f"ERROR: Cannot connect to server: {e}")
            return 1
        
        # Run tests
        success = run_tests(base_url, args.email, args.password, args.verbose)
        return 0 if success else 1
    
    # Start server
    server = ServerManager(args.port, args.host, args.debug)
    
    # Handle signals for cleanup
    def signal_handler(sig, frame):
        print("\nInterrupted, cleaning up...")
        server.stop()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start server
        if not server.start():
            print("ERROR: Failed to start server")
            return 1
        
        # Run tests
        success = run_tests(
            server.base_url,
            args.email,
            args.password,
            args.verbose
        )
        
        return 0 if success else 1
        
    finally:
        # Always stop server
        server.stop()


if __name__ == "__main__":
    sys.exit(main())

