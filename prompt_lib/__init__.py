"""
Prompt Library - A comprehensive system for managing LLM prompts

This package provides a complete solution for storing, editing, retrieving, and composing
LLM prompts with advanced features like template processing, validation, and analytics.

Key Components:
- PromptManager: Core CRUD operations and prompt composition
- PromptTemplate: Advanced templating with conditional logic and loops
- Utilities: Discovery, migration, validation, and optimization tools

Features:
- Store prompts with metadata and categorization
- Compose prompts by including other prompts as sub-parts
- Advanced template processing with control structures
- Persistent JSON storage with backup/restore
- Prompt discovery and migration from existing codebases
- Validation and optimization tools
- Search and analytics capabilities

Example Usage:
    from prompt_lib import WrappedManager, create_wrapped_manager
    
    # Create a wrapped manager (dictionary-like interface)
    manager = create_wrapped_manager("my_prompts.json")
    
    # Store prompts using dictionary syntax
    manager["greeting"] = "Hello, {name}! How can I help you today?"
    manager["farewell"] = "Thank you, {name}. Have a great day!"
    manager["conversation"] = "{greeting} Let me know what you need. {farewell}"
    
    # Get composed prompts automatically
    conversation = manager["conversation"]
    # Result: "Hello, {name}! How can I help you today? Let me know what you need. Thank you, {name}. Have a great day!"
    
    # Use with context
    final = manager.compose("conversation", name="Alice")
    # Result: "Hello, Alice! How can I help you today? Let me know what you need. Thank you, Alice. Have a great day!"

Author: AI Assistant
Created: 2025
Version: 1.0.0
"""

from .prompt_manager import (
    PromptManager,
    PromptValidationError,
    PromptNotFoundError
)

from .prompt_template import (
    PromptTemplate,
    TemplateLibrary,
    TemplateError,
    TemplateValidationError
)

from .wrapped_manager import (
    WrappedManager,
    create_wrapped_manager
)

from .auto_inject import (
    AutoInjector,
    get_default_injector,
    inject,
    register_global_injector
)

from .utils import (
    discover_prompts_in_file,
    discover_prompts_in_directory,
    migrate_from_prompts_py,
    validate_prompt_content,
    analyze_prompt_usage,
    backup_prompts,
    restore_prompts,
    create_prompt_from_template,
    find_prompt_dependencies,
    optimize_prompt_library
)

# Package metadata
__version__ = "1.0.0"
__author__ = "AI Assistant"
__description__ = "A comprehensive system for managing LLM prompts with composition and templating"

# Convenience aliases
PM = PromptManager  # Short alias for PromptManager
PT = PromptTemplate  # Short alias for PromptTemplate

# Default instances for quick usage
_default_manager = None


def get_default_manager(storage_path: str = "prompts.json") -> PromptManager:
    """
    Get or create the default PromptManager instance.
    
    This provides a convenient way to use a singleton PromptManager
    across your application without manually managing the instance.
    
    Args:
        storage_path (str): Path for the JSON storage file
    
    Returns:
        PromptManager: The default PromptManager instance
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = PromptManager(storage_path)
    return _default_manager


def quick_store(name: str, content: str, **kwargs) -> None:
    """
    Quickly store a prompt using the default manager.
    
    Args:
        name (str): Prompt name
        content (str): Prompt content
        **kwargs: Additional arguments passed to store_prompt
    """
    manager = get_default_manager()
    manager.store_prompt(name, content, **kwargs)


def quick_get(name: str, as_dict: bool = False) -> str:
    """
    Quickly retrieve a prompt using the default manager.
    
    Args:
        name (str): Prompt name
        as_dict (bool): Return full dictionary if True
    
    Returns:
        str: Prompt content or dictionary
    """
    manager = get_default_manager()
    return manager.get_prompt(name, as_dict=as_dict)


def quick_compose(name: str, **kwargs) -> str:
    """
    Quickly compose a prompt using the default manager.
    
    Args:
        name (str): Prompt name
        **kwargs: Context variables for composition
    
    Returns:
        str: Composed prompt content
    """
    manager = get_default_manager()
    return manager.compose_prompt(name, **kwargs)


# Export all public classes and functions
__all__ = [
    # Core classes
    "PromptManager",
    "PromptTemplate", 
    "TemplateLibrary",
    "WrappedManager",
    "AutoInjector",
    
    # Exceptions
    "PromptValidationError",
    "PromptNotFoundError",
    "TemplateError",
    "TemplateValidationError",
    
    # Utility functions
    "discover_prompts_in_file",
    "discover_prompts_in_directory", 
    "migrate_from_prompts_py",
    "validate_prompt_content",
    "analyze_prompt_usage",
    "backup_prompts",
    "restore_prompts",
    "create_prompt_from_template",
    "find_prompt_dependencies",
    "optimize_prompt_library",
    
    # Convenience functions
    "get_default_manager",
    "quick_store",
    "quick_get", 
    "quick_compose",
    "create_wrapped_manager",
    "get_default_injector",
    "inject",
    "register_global_injector",
    
    # Aliases
    "PM",
    "PT",
    
    # Package metadata
    "__version__",
    "__author__",
    "__description__"
]


# Package-level configuration
class Config:
    """Package-level configuration settings."""
    
    # Default storage settings
    DEFAULT_STORAGE_PATH = "prompts.json"
    DEFAULT_BACKUP_PATH = "prompts_backup.json"
    
    # Validation settings
    MAX_PROMPT_LENGTH = 50000  # Maximum prompt length in characters
    MIN_PROMPT_LENGTH = 5      # Minimum prompt length in characters
    
    # Discovery settings
    DISCOVERY_FILE_EXTENSIONS = ['.py', '.txt', '.md']
    DISCOVERY_EXCLUDE_DIRS = ['__pycache__', '.git', '.venv', 'venv', 'node_modules']
    
    # Template settings
    TEMPLATE_MAX_RECURSION_DEPTH = 10
    TEMPLATE_STRICT_MODE = True
    
    @classmethod
    def set_default_storage_path(cls, path: str):
        """Set the default storage path for new PromptManager instances."""
        cls.DEFAULT_STORAGE_PATH = path
    
    @classmethod
    def set_validation_limits(cls, min_length: int, max_length: int):
        """Set validation limits for prompt content."""
        cls.MIN_PROMPT_LENGTH = min_length
        cls.MAX_PROMPT_LENGTH = max_length


# Initialize configuration
config = Config()

# Welcome message for interactive usage
def _print_welcome():
    """Print welcome message when imported interactively."""
    try:
        # Only print in interactive environments
        import sys
        if hasattr(sys, 'ps1'):
            print(f"Prompt Library v{__version__} loaded successfully!")
            print("Quick start:")
            print("  from prompt_lib import quick_store, quick_get, quick_compose")
            print("  quick_store('hello', 'Hello, {name}!')")
            print("  quick_compose('hello', name='World')")
    except:
        pass

# Print welcome message
_print_welcome()
