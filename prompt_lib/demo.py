#!/usr/bin/env python3
"""
Demo script for the Prompt Library WrappedManager

This script demonstrates the key features of the WrappedManager,
showing how it provides a dictionary-like interface with automatic
prompt composition.

Run with: python -m prompt_lib.demo

Author: AI Assistant
Created: 2025
"""

import os
import tempfile
from .wrapped_manager import create_wrapped_manager


def main():
    """Run the main demonstration."""
    print("🎯 Prompt Library WrappedManager Demo")
    print("=" * 40)
    
    # Create a temporary file for this demo
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file.close()
    temp_path = temp_file.name
    
    try:
        # Step 1: Create the wrapped manager
        print("\n1️⃣ Creating WrappedManager...")
        manager = create_wrapped_manager(temp_path)
        print(f"   ✅ Created manager with storage: {temp_path}")
        
        # Step 2: Store prompts using dictionary syntax
        print("\n2️⃣ Storing prompts using dictionary syntax...")
        manager["greeting"] = "Hello, {name}! Welcome to {system}."
        manager["farewell"] = "Thank you for using {system}, {name}. Have a great day!"
        manager["help_offer"] = "How can I help you today?"
        manager["conversation"] = "{greeting} {help_offer} {farewell}"
        
        print(f"   ✅ Stored {len(manager)} prompts")
        print(f"   📝 Prompt names: {list(manager.keys())}")
        
        # Step 3: Demonstrate automatic composition
        print("\n3️⃣ Demonstrating automatic composition...")
        raw_conversation = manager.get_raw("conversation")
        composed_conversation = manager["conversation"]
        
        print(f"   📄 Raw prompt: {raw_conversation}")
        print(f"   🔄 Composed prompt: {composed_conversation}")
        
        # Step 4: Use composed prompt with context
        print("\n4️⃣ Using composed prompt with context...")
        final_prompt = manager.compose("conversation", name="Alice", system="ChatGPT")
        print(f"   🎯 Final prompt: {final_prompt}")
        
        # Step 5: Dictionary operations
        print("\n5️⃣ Dictionary operations...")
        print(f"   🔍 'greeting' in manager: {'greeting' in manager}")
        print(f"   🔍 'missing' in manager: {'missing' in manager}")
        print(f"   📊 Length: {len(manager)}")
        print(f"   🔄 Keys: {list(manager.keys())[:3]}...")  # Show first 3
        
        # Step 6: Update and modify
        print("\n6️⃣ Update and modify prompts...")
        manager["new_prompt"] = "This is a new prompt with {variable}."
        manager["greeting"] = "Hi there, {name}! Welcome to {system}."  # Update existing
        
        print(f"   ✅ Added new prompt, updated greeting")
        print(f"   📊 Now have {len(manager)} prompts")
        
        # Show updated composition
        updated_conversation = manager["conversation"]
        print(f"   🔄 Updated conversation: {updated_conversation}")
        
        # Step 7: Advanced features
        print("\n7️⃣ Advanced features...")
        
        # Search
        search_results = manager.search("help")
        print(f"   🔍 Search for 'help': {search_results}")
        
        # Auto-compose toggle
        print(f"   🔄 With auto-compose: {manager['conversation'][:50]}...")
        manager.auto_compose = False
        print(f"   📄 Without auto-compose: {manager['conversation']}")
        manager.auto_compose = True
        
        # Analytics
        analysis = manager.analyze()
        print(f"   📊 Analysis - Total: {analysis['total_prompts']}, Categories: {len(analysis['categories'])}")
        
        # Step 8: Real-world example
        print("\n8️⃣ Real-world example - Email templates...")
        
        # Create email template system
        manager["email_header"] = "Subject: {subject}\nFrom: {sender}\nTo: {recipient}\n"
        manager["email_greeting"] = "Dear {recipient_name},"
        manager["email_closing"] = "Best regards,\n{sender_name}"
        manager["email_template"] = "{email_header}\n{email_greeting}\n\n{body}\n\n{email_closing}"
        
        # Use the email template
        email = manager.compose("email_template", 
                               subject="Meeting Reminder",
                               sender="assistant@company.com",
                               recipient="alice@company.com",
                               recipient_name="Alice",
                               sender_name="AI Assistant",
                               body="This is a reminder about our meeting tomorrow at 2 PM.")
        
        print("   📧 Generated email:")
        print("   " + "\n   ".join(email.split("\n")))
        
        print(f"\n✅ Demo completed successfully!")
        print(f"   📁 Temporary storage used: {temp_path}")
        print(f"   🗑️  Will be cleaned up automatically")
        
    except Exception as e:
        print(f"\n❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        if os.path.exists(temp_path):
            os.unlink(temp_path)
            print(f"   🗑️  Cleaned up temporary file")


if __name__ == "__main__":
    main()
