"""
Prompt Library Manager

This module provides a comprehensive system for storing, editing, retrieving, and composing
LLM prompts. It supports both simple string prompts and complex structured prompts with
composability features using Python string formatting.

Key Features:
- Store and retrieve prompts by name
- Edit existing prompts
- Compose prompts by including other prompts as sub-parts
- Return prompts in Python dictionary format
- Persistent JSON file storage
- Template validation and error handling

Author: AI Assistant
Created: 2025
"""

import json
import os
from typing import Dict, Any, Optional, List, Union
from copy import deepcopy
import re
from datetime import datetime


class PromptValidationError(Exception):
    """Custom exception for prompt validation errors."""
    pass


class PromptNotFoundError(Exception):
    """Custom exception for when a prompt is not found."""
    pass


class PromptManager:
    """
    A comprehensive manager for LLM prompts with storage, editing, retrieval, and composition capabilities.
    
    This class provides a centralized system for managing prompts with the following features:
    - Store prompts with metadata (creation time, last modified, description, etc.)
    - Edit existing prompts
    - Retrieve prompts by name
    - Compose prompts by including other prompts using Python string formatting
    - Return prompts as dictionaries for easy integration
    - Persistent storage using JSON files
    
    The manager supports both simple string prompts and complex structured prompts.
    Composability is achieved through Python string formatting, allowing prompts to
    reference other prompts using placeholders like {prompt_name}.
    """
    
    def __init__(self, storage_path: str = "prompts.json"):
        """
        Initialize the PromptManager with a storage backend.
        
        Args:
            storage_path (str): Path to the JSON file for storing prompts.
                               Defaults to "prompts.json" in the current directory.
        """
        self.storage_path = storage_path
        self._prompts: Dict[str, Dict[str, Any]] = {}
        self._file_mtime = None  # Track file modification time
        self._load_prompts()
    
    def _load_prompts(self) -> None:
        """
        Load prompts from the storage file.
        
        Creates an empty storage file if it doesn't exist.
        Handles JSON parsing errors gracefully.
        """
        try:
            if os.path.exists(self.storage_path):
                # Update file modification time
                self._file_mtime = os.path.getmtime(self.storage_path)
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    self._prompts = json.load(f)
            else:
                self._prompts = {}
                self._save_prompts()  # Create empty file
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load prompts from {self.storage_path}: {e}")
            self._prompts = {}
    
    def _save_prompts(self) -> None:
        """
        Save prompts to the storage file.
        
        Handles file writing errors gracefully and maintains data integrity.
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self._prompts, f, indent=2, ensure_ascii=False)
            
            # Update our tracked modification time
            if os.path.exists(self.storage_path):
                self._file_mtime = os.path.getmtime(self.storage_path)
        except IOError as e:
            print(f"Error: Could not save prompts to {self.storage_path}: {e}")
            raise
    
    def _check_file_changes(self) -> None:
        """
        Check if the storage file has been modified externally and reload if needed.
        
        This ensures that multiple instances of PromptManager stay synchronized
        and that external file modifications are detected.
        """
        try:
            if os.path.exists(self.storage_path):
                current_mtime = os.path.getmtime(self.storage_path)
                if self._file_mtime is None or current_mtime > self._file_mtime:
                    # File has been modified, reload
                    self._load_prompts()
        except OSError:
            # If we can't check the file, continue with current data
            pass
    
    def store_prompt(self, 
                    name: str, 
                    content: str, 
                    description: str = "", 
                    category: str = "general",
                    tags: List[str] = None,
                    metadata: Dict[str, Any] = None) -> None:
        """
        Store a new prompt or update an existing one.
        
        Args:
            name (str): Unique identifier for the prompt
            content (str): The actual prompt text/template
            description (str): Human-readable description of the prompt's purpose
            category (str): Category for organizing prompts (e.g., "research", "coding", "general")
            tags (List[str]): List of tags for better searchability
            metadata (Dict[str, Any]): Additional metadata for the prompt
        
        Raises:
            PromptValidationError: If the prompt name or content is invalid
        """
        if not name or not isinstance(name, str):
            raise PromptValidationError("Prompt name must be a non-empty string")
        
        if not content or not isinstance(content, str):
            raise PromptValidationError("Prompt content must be a non-empty string")
        
        # Initialize default values
        if tags is None:
            tags = []
        if metadata is None:
            metadata = {}
        
        # Check if prompt already exists
        is_update = name in self._prompts
        
        # Create prompt entry
        prompt_entry = {
            "content": content,
            "description": description,
            "category": category,
            "tags": tags,
            "metadata": metadata,
            "created_at": self._prompts.get(name, {}).get("created_at", datetime.now().isoformat()),
            "last_modified": datetime.now().isoformat(),
            "version": self._prompts.get(name, {}).get("version", 0) + 1
        }
        
        self._prompts[name] = prompt_entry
        self._save_prompts()
        
        action = "Updated" if is_update else "Stored"
        print(f"{action} prompt '{name}' successfully")
    
    def get_prompt(self, name: str, as_dict: bool = True) -> Union[str, Dict[str, Any]]:
        """
        Retrieve a prompt by name.
        
        Args:
            name (str): The name of the prompt to retrieve
            as_dict (bool): If True, return the full prompt dictionary including metadata.
                           If False, return only the content string.
        
        Returns:
            Union[str, Dict[str, Any]]: The prompt content or full prompt dictionary
        
        Raises:
            PromptNotFoundError: If the prompt doesn't exist
        """
        # Check for external file changes before reading
        self._check_file_changes()
        
        if name not in self._prompts:
            raise PromptNotFoundError(f"Prompt '{name}' not found")
        
        if as_dict:
            return deepcopy(self._prompts[name])
        else:
            return self._prompts[name]["content"]
    
    def edit_prompt(self, 
                   name: str, 
                   content: Optional[str] = None,
                   description: Optional[str] = None,
                   category: Optional[str] = None,
                   tags: Optional[List[str]] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Edit an existing prompt's properties.
        
        Args:
            name (str): The name of the prompt to edit
            content (str, optional): New content for the prompt
            description (str, optional): New description
            category (str, optional): New category
            tags (List[str], optional): New tags list
            metadata (Dict[str, Any], optional): New metadata
        
        Raises:
            PromptNotFoundError: If the prompt doesn't exist
        """
        if name not in self._prompts:
            raise PromptNotFoundError(f"Prompt '{name}' not found")
        
        prompt_entry = self._prompts[name]
        
        # Update only provided fields
        if content is not None:
            prompt_entry["content"] = content
        if description is not None:
            prompt_entry["description"] = description
        if category is not None:
            prompt_entry["category"] = category
        if tags is not None:
            prompt_entry["tags"] = tags
        if metadata is not None:
            prompt_entry["metadata"] = metadata
        
        # Update modification tracking
        prompt_entry["last_modified"] = datetime.now().isoformat()
        prompt_entry["version"] += 1
        
        self._save_prompts()
        print(f"Edited prompt '{name}' successfully")
    
    def delete_prompt(self, name: str) -> None:
        """
        Delete a prompt.
        
        Args:
            name (str): The name of the prompt to delete
        
        Raises:
            PromptNotFoundError: If the prompt doesn't exist
        """
        if name not in self._prompts:
            raise PromptNotFoundError(f"Prompt '{name}' not found")
        
        del self._prompts[name]
        self._save_prompts()
        print(f"Deleted prompt '{name}' successfully")
    
    def list_prompts(self, 
                    category: Optional[str] = None, 
                    tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all prompts or filter by category/tag.
        
        Args:
            category (str, optional): Filter by category
            tag (str, optional): Filter by tag
        
        Returns:
            List[Dict[str, Any]]: List of prompt dictionaries with metadata
        """
        prompts = []
        
        for name, prompt_data in self._prompts.items():
            # Apply filters
            if category and prompt_data.get("category") != category:
                continue
            if tag and tag not in prompt_data.get("tags", []):
                continue
            
            # Add name to the prompt data for the list
            prompt_info = deepcopy(prompt_data)
            prompt_info["name"] = name
            prompts.append(prompt_info)
        
        # Sort by name
        prompts.sort(key=lambda x: x["name"])
        return prompts
    
    def compose_prompt(self, prompt_name: str, **kwargs) -> str:
        """
        Compose a prompt by substituting placeholders with other prompts or provided values.
        
        This method enables prompt composability by allowing prompts to reference other prompts
        using Python string formatting. Placeholders in the format {prompt_name} are replaced
        with the content of the referenced prompt.
        
        Args:
            prompt_name (str): The name of the main prompt to compose
            **kwargs: Additional keyword arguments for string formatting.
                     These can include values for placeholders or overrides for prompt references.
        
        Returns:
            str: The composed prompt with all placeholders substituted
        
        Raises:
            PromptNotFoundError: If the main prompt or any referenced prompt doesn't exist
            PromptValidationError: If there are circular references or formatting errors
        
        Example:
            # Store prompts
            manager.store_prompt("greeting", "Hello, {name}!")
            manager.store_prompt("farewell", "Goodbye, {name}!")
            manager.store_prompt("conversation", "{greeting} How are you today? {farewell}")
            
            # Compose
            result = manager.compose_prompt("conversation", name="Alice")
            # Result: "Hello, Alice! How are you today? Goodbye, Alice!"
        """
        # Check for external file changes before composing
        self._check_file_changes()
        
        if prompt_name not in self._prompts:
            raise PromptNotFoundError(f"Prompt '{prompt_name}' not found")
        
        # Track visited prompts to detect circular references
        visited = set()
        
        def _resolve_prompt(prompt_name: str, current_visited: set) -> str:
            """Recursively resolve prompt references."""
            if prompt_name in current_visited:
                raise PromptValidationError(f"Circular reference detected: {' -> '.join(current_visited)} -> {prompt_name}")
            
            if prompt_name not in self._prompts:
                raise PromptNotFoundError(f"Referenced prompt '{prompt_name}' not found")
            
            current_visited.add(prompt_name)
            content = self._prompts[prompt_name]["content"]
            
            # Find all placeholder references in the content
            placeholders = re.findall(r'\{([^}]+)\}', content)
            
            substitutions = {}
            for placeholder in placeholders:
                # Check if it's a prompt reference (exists in our prompts) or a regular placeholder
                if placeholder in self._prompts and placeholder not in kwargs:
                    # Recursively resolve the referenced prompt
                    try:
                        substitutions[placeholder] = _resolve_prompt(placeholder, current_visited.copy())
                    except PromptValidationError:
                        # If recursive resolution fails due to missing placeholders, 
                        # get the raw content instead
                        substitutions[placeholder] = self._prompts[placeholder]["content"]
                elif placeholder in kwargs:
                    # Use provided value
                    substitutions[placeholder] = str(kwargs[placeholder])
                # If neither, leave the placeholder as is for string formatting
            
            # Apply substitutions - merge dictionaries with kwargs taking precedence
            try:
                format_context = {**substitutions, **kwargs}
                resolved_content = content.format(**format_context)
            except KeyError as e:
                # If no kwargs provided, only substitute prompt references, leave other placeholders
                if not kwargs and substitutions:
                    # Only format with prompt substitutions, leave other placeholders intact
                    try:
                        resolved_content = content.format(**substitutions)
                    except KeyError:
                        # Some placeholders are not prompt references, do partial formatting
                        resolved_content = content
                        for placeholder, value in substitutions.items():
                            resolved_content = resolved_content.replace(f"{{{placeholder}}}", value)
                else:
                    raise PromptValidationError(f"Missing value for placeholder {e} in prompt '{prompt_name}'")
            except ValueError as e:
                raise PromptValidationError(f"Formatting error in prompt '{prompt_name}': {e}")
            
            current_visited.remove(prompt_name)
            return resolved_content
        
        return _resolve_prompt(prompt_name, visited)
    
    def get_all_prompts(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all prompts as a dictionary.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping prompt names to their data
        """
        # Check for external file changes before reading
        self._check_file_changes()
        return deepcopy(self._prompts)
    
    def search_prompts(self, query: str, search_in: List[str] = None) -> List[Dict[str, Any]]:
        """
        Search for prompts by text query.
        
        Args:
            query (str): Search query string
            search_in (List[str]): Fields to search in. Defaults to ["content", "description", "tags"]
        
        Returns:
            List[Dict[str, Any]]: List of matching prompts with metadata
        """
        if search_in is None:
            search_in = ["content", "description", "tags"]
        
        query_lower = query.lower()
        matching_prompts = []
        
        for name, prompt_data in self._prompts.items():
            match_found = False
            
            for field in search_in:
                if field == "tags":
                    # Search in tags list
                    if any(query_lower in tag.lower() for tag in prompt_data.get("tags", [])):
                        match_found = True
                        break
                else:
                    # Search in string fields
                    field_value = prompt_data.get(field, "")
                    if isinstance(field_value, str) and query_lower in field_value.lower():
                        match_found = True
                        break
            
            if match_found:
                prompt_info = deepcopy(prompt_data)
                prompt_info["name"] = name
                matching_prompts.append(prompt_info)
        
        return matching_prompts
    
    def export_prompts(self, file_path: str, format: str = "json") -> None:
        """
        Export all prompts to a file.
        
        Args:
            file_path (str): Path to the export file
            format (str): Export format ("json" or "yaml")
        """
        if format == "json":
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._prompts, f, indent=2, ensure_ascii=False)
        elif format == "yaml":
            try:
                import yaml
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(self._prompts, f, default_flow_style=False, allow_unicode=True)
            except ImportError:
                raise ImportError("PyYAML is required for YAML export")
        else:
            raise ValueError(f"Unsupported export format: {format}")
        
        print(f"Exported prompts to {file_path} in {format} format")
    
    def import_prompts(self, file_path: str, format: str = "json", merge: bool = True) -> None:
        """
        Import prompts from a file.
        
        Args:
            file_path (str): Path to the import file
            format (str): Import format ("json" or "yaml")
            merge (bool): If True, merge with existing prompts. If False, replace all prompts.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Import file not found: {file_path}")
        
        if format == "json":
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_prompts = json.load(f)
        elif format == "yaml":
            try:
                import yaml
                with open(file_path, 'r', encoding='utf-8') as f:
                    imported_prompts = yaml.safe_load(f)
            except ImportError:
                raise ImportError("PyYAML is required for YAML import")
        else:
            raise ValueError(f"Unsupported import format: {format}")
        
        if not merge:
            self._prompts = {}
        
        # Merge imported prompts
        for name, prompt_data in imported_prompts.items():
            self._prompts[name] = prompt_data
        
        self._save_prompts()
        print(f"Imported {len(imported_prompts)} prompts from {file_path}")
