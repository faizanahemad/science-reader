"""
Test Suite for WrappedManager

This module contains comprehensive tests for the WrappedManager class,
ensuring all dictionary-like operations work correctly and that prompt
composition functions as expected.

Run tests with: python -m pytest test_wrapped_manager.py -v

Author: AI Assistant
Created: 2025
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import json

from .prompt_manager import PromptManager
from .wrapped_manager import WrappedManager, create_wrapped_manager


class TestWrappedManager(unittest.TestCase):
    """Test cases for WrappedManager functionality."""
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create a temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_file.close()
        self.temp_path = self.temp_file.name
        
        # Create manager and wrapped manager
        self.manager = PromptManager(self.temp_path)
        self.wrapped = WrappedManager(self.manager)
        
        # Add some test prompts
        self.test_prompts = {
            "greeting": "Hello, {name}!",
            "farewell": "Goodbye, {name}!",
            "simple": "This is a simple prompt.",
            "conversation": "{greeting} How are you today? {farewell}"
        }
        
        for name, content in self.test_prompts.items():
            self.manager.store_prompt(name, content)
    
    def tearDown(self):
        """Clean up after each test method."""
        # Remove temporary file
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_getitem_simple_prompt(self):
        """Test getting a simple prompt without composition."""
        result = self.wrapped["simple"]
        self.assertEqual(result, "This is a simple prompt.")
    
    def test_getitem_composed_prompt(self):
        """Test getting a prompt that requires composition."""
        result = self.wrapped["conversation"]
        expected = "Hello, {name}! How are you today? Goodbye, {name}!"
        self.assertEqual(result, expected)
    
    def test_getitem_nonexistent_prompt(self):
        """Test getting a prompt that doesn't exist."""
        with self.assertRaises(KeyError):
            _ = self.wrapped["nonexistent"]
    
    def test_setitem_new_prompt(self):
        """Test setting a new prompt."""
        self.wrapped["new_prompt"] = "This is a new prompt with {placeholder}."
        
        # Check that it was stored
        self.assertIn("new_prompt", self.wrapped)
        self.assertEqual(self.wrapped["new_prompt"], "This is a new prompt with {placeholder}.")
    
    def test_setitem_update_existing(self):
        """Test updating an existing prompt."""
        original = self.wrapped["simple"]
        self.wrapped["simple"] = "Updated simple prompt."
        
        # Check that it was updated
        self.assertEqual(self.wrapped["simple"], "Updated simple prompt.")
        self.assertNotEqual(self.wrapped["simple"], original)
    
    def test_setitem_invalid_type(self):
        """Test setting a prompt with invalid type."""
        with self.assertRaises(TypeError):
            self.wrapped["invalid"] = 123
    
    def test_delitem_existing_prompt(self):
        """Test deleting an existing prompt."""
        self.assertIn("simple", self.wrapped)
        del self.wrapped["simple"]
        self.assertNotIn("simple", self.wrapped)
    
    def test_delitem_nonexistent_prompt(self):
        """Test deleting a prompt that doesn't exist."""
        with self.assertRaises(KeyError):
            del self.wrapped["nonexistent"]
    
    def test_contains_existing_prompt(self):
        """Test checking if a prompt exists."""
        self.assertTrue("simple" in self.wrapped)
        self.assertFalse("nonexistent" in self.wrapped)
    
    def test_len(self):
        """Test getting the number of prompts."""
        self.assertEqual(len(self.wrapped), len(self.test_prompts))
        
        # Add a prompt and check length increases
        self.wrapped["new"] = "New prompt"
        self.assertEqual(len(self.wrapped), len(self.test_prompts) + 1)
    
    def test_iter(self):
        """Test iterating over prompt names."""
        names = list(self.wrapped)
        self.assertEqual(set(names), set(self.test_prompts.keys()))
    
    def test_keys(self):
        """Test getting all prompt names."""
        keys = self.wrapped.keys()
        self.assertEqual(set(keys), set(self.test_prompts.keys()))
    
    def test_values(self):
        """Test getting all prompt values (with composition)."""
        values = self.wrapped.values()
        self.assertEqual(len(values), len(self.test_prompts))
        
        # Check that conversation is composed
        conversation_value = None
        for i, key in enumerate(self.wrapped.keys()):
            if key == "conversation":
                conversation_value = values[i]
                break
        
        self.assertIsNotNone(conversation_value)
        self.assertEqual(conversation_value, "Hello, {name}! How are you today? Goodbye, {name}!")
    
    def test_items(self):
        """Test getting all prompt name-value pairs."""
        items = self.wrapped.items()
        self.assertEqual(len(items), len(self.test_prompts))
        
        # Convert to dict for easier checking
        items_dict = dict(items)
        self.assertEqual(items_dict["simple"], "This is a simple prompt.")
        self.assertEqual(items_dict["conversation"], "Hello, {name}! How are you today? Goodbye, {name}!")
    
    def test_get_existing_prompt(self):
        """Test getting a prompt with get method."""
        result = self.wrapped.get("simple")
        self.assertEqual(result, "This is a simple prompt.")
    
    def test_get_nonexistent_prompt_with_default(self):
        """Test getting a nonexistent prompt with default value."""
        result = self.wrapped.get("nonexistent", "default value")
        self.assertEqual(result, "default value")
    
    def test_get_nonexistent_prompt_no_default(self):
        """Test getting a nonexistent prompt without default."""
        result = self.wrapped.get("nonexistent")
        self.assertIsNone(result)
    
    def test_pop_existing_prompt(self):
        """Test popping an existing prompt."""
        original_len = len(self.wrapped)
        result = self.wrapped.pop("simple")
        
        self.assertEqual(result, "This is a simple prompt.")
        self.assertNotIn("simple", self.wrapped)
        self.assertEqual(len(self.wrapped), original_len - 1)
    
    def test_pop_nonexistent_prompt_with_default(self):
        """Test popping a nonexistent prompt with default."""
        result = self.wrapped.pop("nonexistent", "default")
        self.assertEqual(result, "default")
    
    def test_pop_nonexistent_prompt_no_default(self):
        """Test popping a nonexistent prompt without default."""
        with self.assertRaises(KeyError):
            self.wrapped.pop("nonexistent")
    
    def test_update_from_dict(self):
        """Test updating prompts from a dictionary."""
        new_prompts = {
            "new1": "New prompt 1",
            "new2": "New prompt 2"
        }
        
        original_len = len(self.wrapped)
        self.wrapped.update(new_prompts)
        
        self.assertEqual(len(self.wrapped), original_len + 2)
        self.assertEqual(self.wrapped["new1"], "New prompt 1")
        self.assertEqual(self.wrapped["new2"], "New prompt 2")
    
    def test_update_from_wrapped_manager(self):
        """Test updating prompts from another WrappedManager."""
        # Create another wrapped manager
        temp_file2 = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        temp_file2.close()
        temp_path2 = temp_file2.name
        
        try:
            manager2 = PromptManager(temp_path2)
            wrapped2 = WrappedManager(manager2)
            
            wrapped2["source1"] = "Source prompt 1"
            wrapped2["source2"] = "Source prompt 2"
            
            original_len = len(self.wrapped)
            self.wrapped.update(wrapped2)
            
            self.assertEqual(len(self.wrapped), original_len + 2)
            self.assertEqual(self.wrapped["source1"], "Source prompt 1")
            self.assertEqual(self.wrapped["source2"], "Source prompt 2")
        
        finally:
            if os.path.exists(temp_path2):
                os.unlink(temp_path2)
    
    def test_clear(self):
        """Test clearing all prompts."""
        self.assertGreater(len(self.wrapped), 0)
        self.wrapped.clear()
        self.assertEqual(len(self.wrapped), 0)
    
    def test_copy(self):
        """Test creating a dictionary copy."""
        copy_dict = self.wrapped.copy()
        
        self.assertIsInstance(copy_dict, dict)
        self.assertEqual(len(copy_dict), len(self.wrapped))
        self.assertEqual(copy_dict["simple"], "This is a simple prompt.")
        self.assertEqual(copy_dict["conversation"], "Hello, {name}! How are you today? Goodbye, {name}!")
    
    def test_setdefault_new_prompt(self):
        """Test setdefault with a new prompt."""
        result = self.wrapped.setdefault("new_default", "Default content")
        
        self.assertEqual(result, "Default content")
        self.assertIn("new_default", self.wrapped)
        self.assertEqual(self.wrapped["new_default"], "Default content")
    
    def test_setdefault_existing_prompt(self):
        """Test setdefault with an existing prompt."""
        original_value = self.wrapped["simple"]
        result = self.wrapped.setdefault("simple", "This should not be used")
        
        self.assertEqual(result, original_value)
        self.assertEqual(self.wrapped["simple"], original_value)
    
    def test_get_raw(self):
        """Test getting raw prompt content without composition."""
        raw_content = self.wrapped.get_raw("conversation")
        self.assertEqual(raw_content, "{greeting} How are you today? {farewell}")
        
        # Test with dictionary return
        raw_dict = self.wrapped.get_raw("conversation", as_dict=True)
        self.assertIsInstance(raw_dict, dict)
        self.assertEqual(raw_dict["content"], "{greeting} How are you today? {farewell}")
    
    def test_compose_with_context(self):
        """Test composing a prompt with additional context."""
        result = self.wrapped.compose("conversation", name="Alice")
        expected = "Hello, Alice! How are you today? Goodbye, Alice!"
        self.assertEqual(result, expected)
    
    def test_edit_prompt(self):
        """Test editing an existing prompt."""
        self.wrapped.edit("simple", content="Updated simple prompt")
        self.assertEqual(self.wrapped.get_raw("simple"), "Updated simple prompt")
    
    def test_search(self):
        """Test searching for prompts."""
        results = self.wrapped.search("greeting")
        self.assertIn("greeting", results)
        self.assertIn("conversation", results)  # Contains greeting reference
    
    def test_auto_compose_property(self):
        """Test the auto_compose property."""
        self.assertTrue(self.wrapped.auto_compose)
        
        # Disable auto-compose
        self.wrapped.auto_compose = False
        self.assertFalse(self.wrapped.auto_compose)
        
        # Now getting conversation should return raw content
        result = self.wrapped["conversation"]
        self.assertEqual(result, "{greeting} How are you today? {farewell}")
        
        # Re-enable auto-compose
        self.wrapped.auto_compose = True
        result = self.wrapped["conversation"]
        self.assertEqual(result, "Hello, {name}! How are you today? Goodbye, {name}!")
    
    def test_manager_property(self):
        """Test accessing the underlying manager."""
        self.assertIs(self.wrapped.manager, self.manager)
    
    def test_repr_and_str(self):
        """Test string representations."""
        repr_str = repr(self.wrapped)
        self.assertIn("WrappedManager", repr_str)
        self.assertIn("prompts=", repr_str)
        self.assertIn("auto_compose=", repr_str)
        
        str_str = str(self.wrapped)
        self.assertIn("WrappedManager", str_str)


class TestCreateWrappedManager(unittest.TestCase):
    """Test cases for the create_wrapped_manager convenience function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_file.close()
        self.temp_path = self.temp_file.name
    
    def tearDown(self):
        """Clean up after tests."""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_create_wrapped_manager(self):
        """Test creating a wrapped manager with the convenience function."""
        wrapped = create_wrapped_manager(self.temp_path)
        
        self.assertIsInstance(wrapped, WrappedManager)
        self.assertTrue(wrapped.auto_compose)
        
        # Test that it works
        wrapped["test"] = "Test prompt"
        self.assertEqual(wrapped["test"], "Test prompt")
    
    def test_create_wrapped_manager_no_auto_compose(self):
        """Test creating a wrapped manager without auto-composition."""
        wrapped = create_wrapped_manager(self.temp_path, auto_compose=False)
        
        self.assertIsInstance(wrapped, WrappedManager)
        self.assertFalse(wrapped.auto_compose)


class TestWrappedManagerIntegration(unittest.TestCase):
    """Integration tests for WrappedManager with complex scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        self.temp_file.close()
        self.temp_path = self.temp_file.name
        
        self.wrapped = create_wrapped_manager(self.temp_path)
    
    def tearDown(self):
        """Clean up after tests."""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_complex_composition_chain(self):
        """Test complex prompt composition with multiple levels."""
        # Create a chain of prompts that reference each other
        self.wrapped["base"] = "Hello"
        self.wrapped["middle"] = "{base}, {name}"
        self.wrapped["top"] = "{middle}! Welcome to our system."
        
        result = self.wrapped["top"]
        expected = "Hello, {name}! Welcome to our system."
        self.assertEqual(result, expected)
    
    def test_circular_reference_handling(self):
        """Test handling of circular references in prompts."""
        self.wrapped["prompt_a"] = "A: {prompt_b}"
        self.wrapped["prompt_b"] = "B: {prompt_a}"
        
        # This should handle the circular reference gracefully
        # The exact behavior depends on the implementation
        try:
            result = self.wrapped["prompt_a"]
            # If it succeeds, it should have handled the circular reference
            self.assertIsInstance(result, str)
        except Exception as e:
            # If it fails, it should be a validation error, not a crash
            self.assertIn("circular", str(e).lower())
    
    def test_persistence_across_instances(self):
        """Test that prompts persist across different WrappedManager instances."""
        # Store prompts in first instance
        self.wrapped["persistent"] = "This should persist"
        self.wrapped["composed"] = "Composed: {persistent}"
        
        # Create new instance with same storage
        wrapped2 = create_wrapped_manager(self.temp_path)
        
        # Check that prompts are available and composed correctly
        self.assertEqual(wrapped2["persistent"], "This should persist")
        self.assertEqual(wrapped2["composed"], "Composed: This should persist")
    
    def test_mixed_operations(self):
        """Test mixing dictionary operations with manager operations."""
        # Use dictionary-style operations
        self.wrapped["dict_style"] = "Set with dict syntax"
        
        # Use manager-style operations
        self.wrapped.manager.store_prompt("manager_style", "Set with manager", category="test")
        
        # Both should be accessible
        self.assertEqual(self.wrapped["dict_style"], "Set with dict syntax")
        self.assertEqual(self.wrapped["manager_style"], "Set with manager")
        
        # Check that manager metadata is preserved
        raw_data = self.wrapped.get_raw("manager_style", as_dict=True)
        self.assertEqual(raw_data["category"], "test")
    
    def test_multi_instance_synchronization(self):
        """Test that multiple WrappedManager instances stay synchronized."""
        # Create first instance and store data
        self.wrapped["sync_test"] = "Original value"
        
        # Create second instance with same storage file
        wrapped2 = create_wrapped_manager(self.temp_path)
        
        # Second instance should see the data from first instance
        self.assertEqual(wrapped2["sync_test"], "Original value")
        
        # Modify through first instance
        self.wrapped["sync_test"] = "Modified by first instance"
        
        # Second instance should see the change
        self.assertEqual(wrapped2["sync_test"], "Modified by first instance")
        
        # Modify through second instance
        wrapped2["sync_test"] = "Modified by second instance"
        
        # First instance should see the change
        self.assertEqual(self.wrapped["sync_test"], "Modified by second instance")
    
    def test_external_file_modification_detection(self):
        """Test detection of external file modifications."""
        import json
        import time
        
        # Store initial data
        self.wrapped["external_test"] = "Initial value"
        initial_value = self.wrapped["external_test"]
        
        # Modify the file directly
        with open(self.temp_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data["external_test"]["content"] = "Externally modified"
        
        # Small delay to ensure timestamp changes
        time.sleep(0.1)
        
        with open(self.temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        # WrappedManager should detect the external change
        updated_value = self.wrapped["external_test"]
        self.assertNotEqual(updated_value, initial_value)
        self.assertEqual(updated_value, "Externally modified")
    
    def test_persistence_and_reload(self):
        """Test that data persists and reloads correctly."""
        # Store test data
        test_data = {
            "prompt1": "Content 1",
            "prompt2": "Content 2", 
            "composed": "{prompt1} and {prompt2}"
        }
        
        for name, content in test_data.items():
            self.wrapped[name] = content
        
        # Verify composition works
        composed = self.wrapped["composed"]
        expected = "Content 1 and Content 2"
        self.assertEqual(composed, expected)
        
        # Create new instance (simulating restart)
        wrapped_new = create_wrapped_manager(self.temp_path)
        
        # All data should be available
        for name, expected_content in test_data.items():
            if name == "composed":
                # Composed prompt should still compose correctly
                actual = wrapped_new[name]
                self.assertEqual(actual, "Content 1 and Content 2")
            else:
                actual = wrapped_new[name]
                self.assertEqual(actual, expected_content)
        
        # Verify metadata is preserved
        raw_data = wrapped_new.get_raw("prompt1", as_dict=True)
        self.assertIn("created_at", raw_data)
        self.assertIn("last_modified", raw_data)
        self.assertIn("version", raw_data)
    
    def test_concurrent_modifications(self):
        """Test handling of sequential modifications across instances."""
        import time
        
        # Store initial data through first instance
        self.wrapped["shared_prompt"] = "Initial value"
        
        # Create second instance
        wrapped2 = create_wrapped_manager(self.temp_path)
        
        # Verify second instance sees initial data
        self.assertEqual(wrapped2["shared_prompt"], "Initial value")
        
        # Modify through first instance
        self.wrapped["shared_prompt"] = "Modified by first"
        time.sleep(0.1)  # Allow file sync
        
        # Second instance should see the change
        self.assertEqual(wrapped2["shared_prompt"], "Modified by first")
        
        # Modify through second instance
        wrapped2["shared_prompt"] = "Modified by second"
        time.sleep(0.1)  # Allow file sync
        
        # First instance should see the change
        self.assertEqual(self.wrapped["shared_prompt"], "Modified by second")
        
        # Test with different prompts
        self.wrapped["prompt_a"] = "Value A"
        time.sleep(0.15)  # Allow first write to complete
        wrapped2["prompt_b"] = "Value B"
        time.sleep(0.15)  # Allow second write to complete
        
        # Both should see both prompts
        self.assertEqual(self.wrapped["prompt_b"], "Value B")
        self.assertEqual(wrapped2["prompt_a"], "Value A")
    
    def test_file_corruption_recovery(self):
        """Test graceful handling of corrupted files."""
        # Store some data first
        self.wrapped["recovery_test"] = "Original data"
        
        # Corrupt the file
        with open(self.temp_path, 'w') as f:
            f.write("{ invalid json")
        
        # Create new instance - should handle corruption gracefully
        wrapped_new = create_wrapped_manager(self.temp_path)
        
        # Should start with empty data but not crash
        self.assertEqual(len(wrapped_new), 0)
        
        # Should be able to store new data
        wrapped_new["new_data"] = "After recovery"
        self.assertEqual(wrapped_new["new_data"], "After recovery")


def run_comprehensive_example():
    """
    Run a comprehensive example demonstrating all WrappedManager features.
    This function serves as both a test and documentation.
    """
    print("=== WrappedManager Comprehensive Example ===\n")
    
    # Create a temporary file for this example
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file.close()
    temp_path = temp_file.name
    
    try:
        # Create wrapped manager
        print("1. Creating WrappedManager...")
        wrapped = create_wrapped_manager(temp_path)
        print(f"   Created: {wrapped}")
        
        # Store prompts using dictionary syntax
        print("\n2. Storing prompts using dictionary syntax...")
        wrapped["greeting"] = "Hello, {name}! Welcome to {system}."
        wrapped["farewell"] = "Thank you for using {system}, {name}!"
        wrapped["help_offer"] = "How can I help you today?"
        wrapped["conversation"] = "{greeting} {help_offer} {farewell}"
        
        print(f"   Stored {len(wrapped)} prompts")
        print(f"   Prompt names: {list(wrapped.keys())}")
        
        # Demonstrate automatic composition
        print("\n3. Demonstrating automatic composition...")
        conversation = wrapped["conversation"]
        print(f"   Raw conversation prompt: {wrapped.get_raw('conversation')}")
        print(f"   Composed conversation: {conversation}")
        
        # Use the composed prompt with context
        print("\n4. Using composed prompt with context...")
        final_prompt = wrapped.compose("conversation", name="Alice", system="ChatGPT")
        print(f"   Final prompt: {final_prompt}")
        
        # Demonstrate dictionary operations
        print("\n5. Demonstrating dictionary operations...")
        print(f"   'greeting' in wrapped: {'greeting' in wrapped}")
        print(f"   wrapped.get('nonexistent', 'default'): {wrapped.get('nonexistent', 'default')}")
        
        # Update prompts
        print("\n6. Updating prompts...")
        wrapped.update({
            "new_prompt": "This is a new prompt",
            "another": "Another prompt with {variable}"
        })
        print(f"   Now have {len(wrapped)} prompts")
        
        # Search functionality
        print("\n7. Search functionality...")
        search_results = wrapped.search("help")
        print(f"   Prompts containing 'help': {search_results}")
        
        # Advanced features
        print("\n8. Advanced features...")
        analysis = wrapped.analyze()
        print(f"   Total prompts: {analysis['total_prompts']}")
        print(f"   Categories: {analysis['categories']}")
        
        print("\n9. Auto-compose toggle...")
        print(f"   With auto-compose: {wrapped['conversation']}")
        wrapped.auto_compose = False
        print(f"   Without auto-compose: {wrapped['conversation']}")
        wrapped.auto_compose = True
        
        print("\n=== Example completed successfully! ===")
        
    finally:
        # Clean up
        if os.path.exists(temp_path):
            os.unlink(temp_path)


if __name__ == "__main__":
    # Run the comprehensive example
    run_comprehensive_example()
    
    print("\n" + "="*50)
    print("Running unit tests...")
    print("="*50)
    
    # Run unit tests
    unittest.main(verbosity=2)
