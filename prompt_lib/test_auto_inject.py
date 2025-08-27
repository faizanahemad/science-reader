#!/usr/bin/env python3
"""
Test and demonstration script for the Auto-injection System

This script demonstrates all the features of the auto-injection system
including default injectors, custom injectors, and integration with
the WrappedManager.

Run with: python -m prompt_lib.test_auto_inject

Author: AI Assistant
Created: 2025
"""

import tempfile
import os
from datetime import datetime
from .auto_inject import AutoInjector, get_default_injector, inject
from .wrapped_manager import create_wrapped_manager


def test_basic_injection():
    """Test basic auto-injection functionality."""
    print("\n🔧 Testing Basic Auto-injection")
    print("=" * 40)
    
    injector = AutoInjector()
    
    # Test with date placeholder
    prompt = "Today is {date}. The current time is {time}."
    result = injector.inject(prompt)
    print(f"Original: {prompt}")
    print(f"Injected: {result}")
    assert "{date}" not in result
    assert "{time}" not in result
    print("✅ Basic injection works!")


def test_selective_injection():
    """Test selective injection with only/exclude options."""
    print("\n🎯 Testing Selective Injection")
    print("=" * 40)
    
    injector = AutoInjector()
    
    prompt = "User: {user}, Date: {date}, Time: {time}, System: {system}"
    
    # Inject only date and time
    result = injector.inject_selective(prompt, only=["date", "time"])
    print(f"Only date/time: {result}")
    assert "{user}" in result  # Should remain
    assert "{system}" in result  # Should remain
    assert "{date}" not in result  # Should be injected
    assert "{time}" not in result  # Should be injected
    
    # Exclude user and system
    result = injector.inject_selective(prompt, exclude=["user", "system"])
    print(f"Exclude user/system: {result}")
    assert "{user}" in result  # Should remain
    assert "{system}" in result  # Should remain
    assert "{date}" not in result  # Should be injected
    assert "{time}" not in result  # Should be injected
    
    print("✅ Selective injection works!")


def test_custom_injector():
    """Test adding custom injectors."""
    print("\n🛠️ Testing Custom Injectors")
    print("=" * 40)
    
    injector = AutoInjector()
    
    # Add custom injector
    def greeting_injector():
        hour = datetime.now().hour
        if hour < 12:
            return "Good morning"
        elif hour < 18:
            return "Good afternoon"
        else:
            return "Good evening"
    
    injector.register_injector("greeting", greeting_injector, 
                              description="Time-based greeting")
    
    prompt = "{greeting}! Today is {short_date}."
    result = injector.inject(prompt)
    print(f"Original: {prompt}")
    print(f"Injected: {result}")
    assert "{greeting}" not in result
    assert "{short_date}" not in result
    print("✅ Custom injector works!")


def test_context_override():
    """Test context value overrides."""
    print("\n🔄 Testing Context Overrides")
    print("=" * 40)
    
    injector = AutoInjector()
    
    prompt = "Hello {user}, today is {date}"
    
    # Inject with context override
    result = injector.inject(prompt, context={"user": "Alice", "date": "Christmas Day"})
    print(f"Original: {prompt}")
    print(f"With overrides: {result}")
    assert "Alice" in result
    assert "Christmas Day" in result
    print("✅ Context overrides work!")


def test_wrapped_manager_integration():
    """Test integration with WrappedManager."""
    print("\n🔗 Testing WrappedManager Integration")
    print("=" * 40)
    
    # Create temporary file for testing
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file.close()
    temp_path = temp_file.name
    
    try:
        # Create manager with auto-injection enabled
        manager = create_wrapped_manager(temp_path, auto_inject=True)
        
        # Store prompts with placeholders
        manager["daily_report"] = "Daily Report for {date}\nPrepared by: {user}\nSystem: {system}"
        manager["greeting"] = "Hello {name}, today is {weekday}"
        manager["composed"] = "{greeting}. {daily_report}"
        
        # Get prompt with auto-injection
        report = manager["daily_report"]
        print("Daily Report (auto-injected):")
        print(report)
        assert "{date}" not in report
        assert "{user}" not in report
        assert "{system}" not in report
        
        # Test composition with injection
        greeting = manager.compose("greeting", name="Bob")
        print(f"\nGreeting with context: {greeting}")
        assert "Bob" in greeting
        assert "{weekday}" not in greeting
        
        # Test disabling injection
        manager.auto_inject = False
        raw_report = manager["daily_report"]
        print(f"\nRaw (no injection): {raw_report}")
        assert "{date}" in raw_report
        assert "{user}" in raw_report
        
        print("✅ WrappedManager integration works!")
        
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_injector_management():
    """Test injector enable/disable and management."""
    print("\n⚙️ Testing Injector Management")
    print("=" * 40)
    
    injector = AutoInjector()
    
    # List enabled injectors
    enabled = injector.list_enabled_injectors()
    print(f"Enabled injectors: {enabled}")
    
    # Disable date injector
    injector.disable_injector("date")
    prompt = "Today is {date}"
    result = injector.inject(prompt)
    print(f"With date disabled: {result}")
    assert "{date}" in result  # Should not be injected
    
    # Re-enable date injector
    injector.enable_injector("date")
    result = injector.inject(prompt)
    print(f"With date re-enabled: {result}")
    assert "{date}" not in result  # Should be injected
    
    # Detect placeholders
    test_prompt = "Hello {user}, today is {date} and time is {time}. {unknown_placeholder}"
    detected = injector.detect_placeholders(test_prompt)
    print(f"Detected placeholders: {detected}")
    assert "user" in detected
    assert "date" in detected
    assert "time" in detected
    assert "unknown_placeholder" not in detected
    
    print("✅ Injector management works!")


def test_all_default_injectors():
    """Test all default injectors."""
    print("\n📋 Testing All Default Injectors")
    print("=" * 40)
    
    injector = AutoInjector()
    
    # Test each default injector
    test_prompts = {
        "date": "Full date: {date}",
        "time": "Time: {time}",
        "short_date": "Short date: {short_date}",
        "timestamp": "Timestamp: {timestamp}",
        "user": "User: {user}",
        "system": "System: {system}",
        "python_version": "Python: {python_version}",
        "cwd": "CWD: {cwd}",
        "weekday": "Weekday: {weekday}",
        "month": "Month: {month}",
        "year": "Year: {year}"
    }
    
    for name, prompt in test_prompts.items():
        result = injector.inject(prompt)
        print(f"{name}: {result}")
        assert f"{{{name}}}" not in result
    
    print("✅ All default injectors work!")


def test_global_injector():
    """Test global injector functions."""
    print("\n🌍 Testing Global Injector")
    print("=" * 40)
    
    # Use global inject function
    prompt = "Today is {date}"
    result = inject(prompt)
    print(f"Global inject: {result}")
    assert "{date}" not in result
    
    # Register global custom injector
    from . import register_global_injector
    
    def custom_global():
        return "GLOBAL_VALUE"
    
    register_global_injector("custom_global", custom_global)
    
    prompt = "Custom: {custom_global}"
    result = inject(prompt)
    print(f"With custom global: {result}")
    assert "GLOBAL_VALUE" in result
    
    print("✅ Global injector works!")


def run_comprehensive_test():
    """Run all tests."""
    print("🚀 Auto-injection System Comprehensive Test")
    print("=" * 50)
    
    try:
        test_basic_injection()
        test_selective_injection()
        test_custom_injector()
        test_context_override()
        test_wrapped_manager_integration()
        test_injector_management()
        test_all_default_injectors()
        test_global_injector()
        
        print("\n" + "=" * 50)
        print("✅ All auto-injection tests passed successfully!")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_comprehensive_test()
