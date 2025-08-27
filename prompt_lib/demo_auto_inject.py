#!/usr/bin/env python3
"""
Demo: Auto-injection System for Dynamic Values in Prompts

This demo shows how to use the auto-injection system to automatically
inject dynamic values like dates, times, and user information into prompts.

Author: AI Assistant
Created: 2025
"""

import tempfile
import os
from prompt_lib import create_wrapped_manager, AutoInjector


def main():
    print("🚀 Auto-injection Demo")
    print("=" * 50)
    
    # Create temporary storage
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file.close()
    temp_path = temp_file.name
    
    try:
        # Create a wrapped manager with auto-injection enabled (default)
        manager = create_wrapped_manager(temp_path)
        
        print("\n1️⃣ Basic Auto-injection")
        print("-" * 30)
        
        # Store a prompt with date placeholder
        manager["daily_prompt"] = """
Good morning! Today's date is {date}.

Please review the following tasks:
- Check emails
- Update project status
- Prepare daily report

Current user: {user}
System: {system}
"""
        
        # Get the prompt - date, user, and system are automatically injected
        result = manager["daily_prompt"]
        print("Prompt with auto-injected values:")
        print(result)
        
        print("\n2️⃣ Custom Injectors")
        print("-" * 30)
        
        # Add a custom injector for project name
        def project_name_injector():
            return "ChatGPT-Iterative Research Project"
        
        manager.injector.register_injector("project", project_name_injector,
                                          description="Current project name")
        
        # Store prompt using custom injector
        manager["project_update"] = """
Project Update: {project}
Date: {short_date}
Time: {time}

Status: In Progress
Next milestone: {milestone}
"""
        
        # Get with partial context
        result = manager.compose("project_update", milestone="v2.0 Release")
        print("Project update with custom injector:")
        print(result)
        
        print("\n3️⃣ Selective Injection")
        print("-" * 30)
        
        # Store a template with multiple placeholders
        manager["template"] = """
Template Report
===============
Date: {date}
User: {user}
Department: {department}
Priority: {priority}
"""
        
        # Use with context overrides
        result = manager.compose("template", 
                               department="Engineering",
                               priority="High",
                               user="John Doe")  # Override the auto-injected user
        print("Template with overrides:")
        print(result)
        
        print("\n4️⃣ Disable Auto-injection")
        print("-" * 30)
        
        # Temporarily disable auto-injection
        manager.auto_inject = False
        raw = manager["daily_prompt"]
        print("Raw prompt (no injection):")
        print(raw[:100] + "...")  # Show first 100 chars
        
        # Re-enable
        manager.auto_inject = True
        
        print("\n5️⃣ Available Injectors")
        print("-" * 30)
        
        # List all available injectors
        injectors = manager.injector.get_injectors()
        print("Available auto-injectors:")
        for name, info in list(injectors.items())[:5]:  # Show first 5
            print(f"  • {name}: {info['description']}")
        print(f"  ... and {len(injectors) - 5} more")
        
        print("\n6️⃣ Real-world Example")
        print("-" * 30)
        
        # Create a realistic prompt template
        manager["llm_system_prompt"] = """
You are an AI assistant helping with research and development.

Current date and time: {date}
User: {user}
Working directory: {cwd}
Python version: {python_version}

Your task is to assist with {task_type} while following these guidelines:
- Be helpful and accurate
- Provide code examples when relevant
- Consider the current context and environment

Please begin by acknowledging the current date and user.
"""
        
        # Use with task context
        result = manager.compose("llm_system_prompt", task_type="code review")
        print("LLM System Prompt:")
        print(result)
        
        print("\n✅ Demo completed successfully!")
        print("=" * 50)
        
    finally:
        # Clean up
        if os.path.exists(temp_path):
            os.unlink(temp_path)


if __name__ == "__main__":
    main()
