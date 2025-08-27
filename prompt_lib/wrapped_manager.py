"""
Dictionary-like Wrapper for PromptManager

This module provides a dictionary-like interface to PromptManager that automatically
handles prompt composition and provides intuitive access patterns. The wrapper
allows you to use prompts like a regular Python dictionary while maintaining
all the advanced features of the underlying PromptManager.

Key Features:
- Dictionary-like access: manager["prompt_name"]
- Automatic composition when retrieving prompts
- Auto-save when setting prompts
- Seamless integration with existing PromptManager functionality
- Support for all PromptManager methods through delegation

Example Usage:
    manager = PromptManager("prompts.json")
    wrapped = WrappedManager(manager)
    
    # Store prompts like dictionary items
    wrapped["greeting"] = "Hello, {name}!"
    wrapped["farewell"] = "Goodbye, {name}!"
    wrapped["conversation"] = "{greeting} How are you? {farewell}"
    
    # Retrieve composed prompts
    conversation = wrapped["conversation"]
    # Returns: "Hello, {name}! How are you? Goodbye, {name}!"

Author: AI Assistant
Created: 2025
"""

from typing import Dict, Any, List, Optional, Iterator, Union
from .prompt_manager import PromptManager, PromptNotFoundError, PromptValidationError
from .auto_inject import AutoInjector


class WrappedManager:
    """
    A dictionary-like wrapper around PromptManager that provides intuitive access
    to prompts with automatic composition and seamless integration.
    
    This wrapper allows you to interact with prompts using familiar dictionary
    syntax while automatically handling prompt composition in the background.
    When you retrieve a prompt that references other prompts, it automatically
    composes them and returns the final result ready for string formatting.
    
    Features:
    - Dictionary-like access: wrapped["prompt_name"]
    - Automatic saving when setting prompts
    - Automatic composition when getting prompts
    - Support for all dictionary operations (keys, values, items, etc.)
    - Delegation to underlying PromptManager for advanced features
    """
    
    def __init__(self, prompt_manager: PromptManager, auto_compose: bool = True, 
                 auto_inject: bool = True, injector: Optional[AutoInjector] = None):
        """
        Initialize the WrappedManager with an existing PromptManager.
        
        Args:
            prompt_manager (PromptManager): The underlying PromptManager instance
            auto_compose (bool): Whether to automatically compose prompts on retrieval
            auto_inject (bool): Whether to automatically inject dynamic values
            injector (Optional[AutoInjector]): Custom injector instance, or None for default
        """
        self._manager = prompt_manager
        self._auto_compose = auto_compose
        self._auto_inject = auto_inject
        self._injector = injector or AutoInjector()
    
    def __getitem__(self, key: str) -> str:
        """
        Get a prompt by name. Automatically composes if the prompt contains references
        and injects dynamic values if enabled.
        
        Args:
            key (str): The prompt name
            
        Returns:
            str: The prompt content (composed and injected if enabled)
            
        Raises:
            KeyError: If the prompt doesn't exist
        """
        try:
            if self._auto_compose:
                # Try to compose the prompt first
                try:
                    result = self._manager.compose_prompt(key)
                except (PromptNotFoundError, PromptValidationError):
                    # If composition fails, fall back to raw content
                    result = self._manager.get_prompt(key, as_dict=False)
            else:
                result = self._manager.get_prompt(key, as_dict=False)
            
            # Apply auto-injection if enabled
            if self._auto_inject:
                result = self._injector.inject(result)
            
            return result
        except PromptNotFoundError:
            raise KeyError(f"Prompt '{key}' not found")
    
    def __setitem__(self, key: str, value: str) -> None:
        """
        Set a prompt and automatically save it.
        
        Args:
            key (str): The prompt name
            value (str): The prompt content
        """
        if not isinstance(value, str):
            raise TypeError(f"Prompt content must be a string, got {type(value)}")
        
        # Store the prompt with auto-save
        self._manager.store_prompt(
            name=key,
            content=value,
            description=f"Set via WrappedManager",
            category="wrapped",
            tags=["wrapped"]
        )
    
    def __delitem__(self, key: str) -> None:
        """
        Delete a prompt.
        
        Args:
            key (str): The prompt name
            
        Raises:
            KeyError: If the prompt doesn't exist
        """
        try:
            self._manager.delete_prompt(key)
        except PromptNotFoundError:
            raise KeyError(f"Prompt '{key}' not found")
    
    def __contains__(self, key: str) -> bool:
        """
        Check if a prompt exists.
        
        Args:
            key (str): The prompt name
            
        Returns:
            bool: True if the prompt exists
        """
        try:
            self._manager.get_prompt(key, as_dict=False)
            return True
        except PromptNotFoundError:
            return False
    
    def __len__(self) -> int:
        """
        Get the number of prompts.
        
        Returns:
            int: Number of prompts
        """
        return len(self._manager.get_all_prompts())
    
    def __iter__(self) -> Iterator[str]:
        """
        Iterate over prompt names.
        
        Returns:
            Iterator[str]: Iterator of prompt names
        """
        return iter(self._manager.get_all_prompts().keys())
    
    def keys(self) -> List[str]:
        """
        Get all prompt names.
        
        Returns:
            List[str]: List of prompt names
        """
        return list(self._manager.get_all_prompts().keys())
    
    def values(self) -> List[str]:
        """
        Get all prompt contents (composed if auto_compose is True).
        
        Returns:
            List[str]: List of prompt contents
        """
        return [self[key] for key in self.keys()]
    
    def items(self) -> List[tuple]:
        """
        Get all prompt name-content pairs.
        
        Returns:
            List[tuple]: List of (name, content) tuples
        """
        return [(key, self[key]) for key in self.keys()]
    
    def get(self, key: str, default: str = None) -> str:
        """
        Get a prompt with a default value if not found.
        
        Args:
            key (str): The prompt name
            default (str): Default value if prompt not found
            
        Returns:
            str: The prompt content or default value
        """
        try:
            return self[key]
        except KeyError:
            return default
    
    def pop(self, key: str, default: str = None) -> str:
        """
        Remove and return a prompt.
        
        Args:
            key (str): The prompt name
            default (str): Default value if prompt not found
            
        Returns:
            str: The prompt content
            
        Raises:
            KeyError: If prompt not found and no default provided
        """
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            if default is not None:
                return default
            raise
    
    def update(self, other: Union[Dict[str, str], 'WrappedManager']) -> None:
        """
        Update prompts from another dictionary or WrappedManager.
        
        Args:
            other (Union[Dict[str, str], WrappedManager]): Source of prompts to update from
        """
        if isinstance(other, WrappedManager):
            for key in other.keys():
                self[key] = other[key]
        elif isinstance(other, dict):
            for key, value in other.items():
                self[key] = value
        else:
            raise TypeError(f"Can only update from dict or WrappedManager, got {type(other)}")
    
    def clear(self) -> None:
        """
        Remove all prompts.
        
        Warning: This will delete all prompts permanently!
        """
        for key in list(self.keys()):
            del self[key]
    
    def copy(self) -> Dict[str, str]:
        """
        Create a dictionary copy of all prompts.
        
        Returns:
            Dict[str, str]: Dictionary of prompt names to contents
        """
        return dict(self.items())
    
    def setdefault(self, key: str, default: str) -> str:
        """
        Get a prompt or set it to a default value if not found.
        
        Args:
            key (str): The prompt name
            default (str): Default prompt content
            
        Returns:
            str: The existing or newly set prompt content
        """
        if key in self:
            return self[key]
        else:
            self[key] = default
            return default
    
    # Delegation methods for advanced PromptManager functionality
    
    def get_raw(self, key: str, as_dict: bool = False) -> Union[str, Dict[str, Any]]:
        """
        Get the raw prompt without composition.
        
        Args:
            key (str): The prompt name
            as_dict (bool): Return full prompt dictionary if True
            
        Returns:
            Union[str, Dict[str, Any]]: Raw prompt content or dictionary
        """
        try:
            return self._manager.get_prompt(key, as_dict=as_dict)
        except PromptNotFoundError:
            raise KeyError(f"Prompt '{key}' not found")
    
    def compose(self, key: str, **kwargs) -> str:
        """
        Compose a prompt with additional context variables and auto-injection.
        
        Args:
            key (str): The prompt name
            **kwargs: Context variables for composition
            
        Returns:
            str: The composed and injected prompt
        """
        try:
            # If auto-injection is enabled, we need to provide injected values
            # to the composition process to avoid missing placeholder errors
            if self._auto_inject:
                # Get the raw prompt to detect what needs injection
                raw_prompt = self._manager.get_prompt(key, as_dict=False)
                detected = self._injector.detect_placeholders(raw_prompt)
                
                # Add injected values to kwargs for any detected placeholders
                # that aren't already in kwargs
                for placeholder in detected:
                    if placeholder not in kwargs and self._injector._injectors[placeholder]["enabled"]:
                        try:
                            kwargs[placeholder] = self._injector._injectors[placeholder]["function"]()
                        except:
                            pass  # If injection fails, let compose handle it
            
            result = self._manager.compose_prompt(key, **kwargs)
            
            # Still apply injection for any remaining placeholders
            if self._auto_inject:
                result = self._injector.inject(result, context=kwargs)
            
            return result
        except PromptNotFoundError:
            raise KeyError(f"Prompt '{key}' not found")
    
    def edit(self, key: str, content: str = None, **kwargs) -> None:
        """
        Edit an existing prompt's properties.
        
        Args:
            key (str): The prompt name
            content (str, optional): New content
            **kwargs: Other properties to update
        """
        try:
            self._manager.edit_prompt(key, content=content, **kwargs)
        except PromptNotFoundError:
            raise KeyError(f"Prompt '{key}' not found")
    
    def search(self, query: str) -> List[str]:
        """
        Search for prompts and return matching names.
        
        Args:
            query (str): Search query
            
        Returns:
            List[str]: List of matching prompt names
        """
        results = self._manager.search_prompts(query)
        return [result["name"] for result in results]
    
    def list_by_category(self, category: str) -> List[str]:
        """
        List prompts in a specific category.
        
        Args:
            category (str): Category name
            
        Returns:
            List[str]: List of prompt names in the category
        """
        prompts = self._manager.list_prompts(category=category)
        return [prompt["name"] for prompt in prompts]
    
    def list_by_tag(self, tag: str) -> List[str]:
        """
        List prompts with a specific tag.
        
        Args:
            tag (str): Tag name
            
        Returns:
            List[str]: List of prompt names with the tag
        """
        prompts = self._manager.list_prompts(tag=tag)
        return [prompt["name"] for prompt in prompts]
    
    def backup(self, backup_path: str) -> bool:
        """
        Create a backup of all prompts.
        
        Args:
            backup_path (str): Path for the backup file
            
        Returns:
            bool: True if backup was successful
        """
        from .utils import backup_prompts
        return backup_prompts(self._manager, backup_path)
    
    def restore(self, backup_path: str, merge: bool = True) -> bool:
        """
        Restore prompts from a backup file.
        
        Args:
            backup_path (str): Path to the backup file
            merge (bool): Whether to merge with existing prompts
            
        Returns:
            bool: True if restore was successful
        """
        from .utils import restore_prompts
        return restore_prompts(self._manager, backup_path, merge)
    
    def analyze(self) -> Dict[str, Any]:
        """
        Analyze prompt usage patterns.
        
        Returns:
            Dict[str, Any]: Analysis results
        """
        from .utils import analyze_prompt_usage
        return analyze_prompt_usage(self._manager)
    
    def optimize(self) -> Dict[str, Any]:
        """
        Get optimization suggestions.
        
        Returns:
            Dict[str, Any]: Optimization report
        """
        from .utils import optimize_prompt_library
        return optimize_prompt_library(self._manager)
    
    @property
    def manager(self) -> PromptManager:
        """
        Access the underlying PromptManager instance.
        
        Returns:
            PromptManager: The underlying prompt manager
        """
        return self._manager
    
    @property
    def auto_compose(self) -> bool:
        """
        Check if auto-composition is enabled.
        
        Returns:
            bool: True if auto-composition is enabled
        """
        return self._auto_compose
    
    @auto_compose.setter
    def auto_compose(self, value: bool) -> None:
        """
        Enable or disable auto-composition.
        
        Args:
            value (bool): Whether to enable auto-composition
        """
        self._auto_compose = value
    
    @property
    def auto_inject(self) -> bool:
        """
        Check if auto-injection is enabled.
        
        Returns:
            bool: True if auto-injection is enabled
        """
        return self._auto_inject
    
    @auto_inject.setter
    def auto_inject(self, value: bool) -> None:
        """
        Enable or disable auto-injection.
        
        Args:
            value (bool): Whether to enable auto-injection
        """
        self._auto_inject = value
    
    @property
    def injector(self) -> AutoInjector:
        """
        Access the AutoInjector instance.
        
        Returns:
            AutoInjector: The injector instance
        """
        return self._injector
    
    def __repr__(self) -> str:
        """String representation of the WrappedManager."""
        return f"WrappedManager(prompts={len(self)}, auto_compose={self._auto_compose})"
    
    def __str__(self) -> str:
        """String representation showing prompt names."""
        prompt_names = list(self.keys())[:5]  # Show first 5
        if len(self) > 5:
            prompt_names.append("...")
        return f"WrappedManager({prompt_names})"


# Convenience function for creating wrapped managers
def create_wrapped_manager(storage_path: str = "prompts.json", 
                          auto_compose: bool = True,
                          auto_inject: bool = True,
                          injector: Optional[AutoInjector] = None) -> WrappedManager:
    """
    Create a new WrappedManager with a PromptManager backend.
    
    Args:
        storage_path (str): Path for the JSON storage file
        auto_compose (bool): Whether to enable auto-composition
        auto_inject (bool): Whether to enable auto-injection
        injector (Optional[AutoInjector]): Custom injector instance
        
    Returns:
        WrappedManager: A new wrapped manager instance
    """
    manager = PromptManager(storage_path)
    return WrappedManager(manager, auto_compose, auto_inject, injector)
