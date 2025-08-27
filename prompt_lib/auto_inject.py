"""
Auto-injection System for Dynamic Prompt Values

This module provides a flexible system for automatically injecting dynamic values
into prompts. It supports configurable injectors that can replace placeholders
like {date}, {time}, {user}, etc. with computed values at runtime.

The system is extensible, allowing easy addition of new injectors without
modifying existing code.

Key Features:
- Automatic detection and replacement of registered placeholders
- Configurable injection (can be enabled/disabled)
- Extensible injector registry
- Built-in injectors for common use cases (date, time, etc.)
- Integration with PromptManager and WrappedManager

Example Usage:
    from prompt_lib import AutoInjector
    
    injector = AutoInjector()
    prompt = "Today is {date}. The time is {time}."
    result = injector.inject(prompt)
    # Result: "Today is 25 December 2024, year is 2024... The time is 14:30:45."

Author: AI Assistant
Created: 2025
"""

import datetime
import calendar
import os
import platform
import getpass
from typing import Dict, Callable, Any, Optional, List
import re
from functools import lru_cache


class AutoInjector:
    """
    A flexible auto-injection system for dynamic prompt values.
    
    This class manages a registry of injectors that can automatically replace
    placeholders in prompts with computed values. It's designed to be extensible
    and configurable.
    
    The injector supports:
    - Registration of custom injector functions
    - Enabling/disabling specific injectors
    - Global enable/disable
    - Caching of expensive computations
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize the AutoInjector with default injectors.
        
        Args:
            enabled (bool): Whether auto-injection is globally enabled
        """
        self.enabled = enabled
        self._injectors: Dict[str, Dict[str, Any]] = {}
        self._cache_enabled = True
        
        # Register default injectors
        self._register_default_injectors()
    
    def _register_default_injectors(self):
        """Register the default set of injectors."""
        
        # Date injector - matches the format from prompts.py
        def date_injector() -> str:
            """Generate a comprehensive date string."""
            date = datetime.datetime.now().strftime("%d %B %Y")
            year = datetime.datetime.now().strftime("%Y")
            month = datetime.datetime.now().strftime("%B")
            day = datetime.datetime.now().strftime("%d")
            weekday = datetime.datetime.now().weekday()
            weekday_name = calendar.day_name[weekday]
            time = datetime.datetime.now().strftime("%H:%M:%S")
            return f"The current date is '{date}', year is {year}, month is {month}, day is {day}. It is a {weekday_name}. The current time is {time}."
        
        # Time injector
        def time_injector() -> str:
            """Generate current time string."""
            return datetime.datetime.now().strftime("%H:%M:%S")
        
        # Short date injector
        def short_date_injector() -> str:
            """Generate short date string."""
            return datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Timestamp injector
        def timestamp_injector() -> str:
            """Generate ISO timestamp."""
            return datetime.datetime.now().isoformat()
        
        # User injector
        def user_injector() -> str:
            """Get current username."""
            try:
                return getpass.getuser()
            except:
                return "user"
        
        # System info injector
        def system_injector() -> str:
            """Get system information."""
            return f"{platform.system()} {platform.release()}"
        
        # Python version injector
        def python_version_injector() -> str:
            """Get Python version."""
            return platform.python_version()
        
        # Working directory injector
        def cwd_injector() -> str:
            """Get current working directory."""
            return os.getcwd()
        
        # Day of week injector
        def weekday_injector() -> str:
            """Get current day of week."""
            weekday = datetime.datetime.now().weekday()
            return calendar.day_name[weekday]
        
        # Month name injector
        def month_injector() -> str:
            """Get current month name."""
            return datetime.datetime.now().strftime("%B")
        
        # Year injector
        def year_injector() -> str:
            """Get current year."""
            return datetime.datetime.now().strftime("%Y")
        
        # Register all default injectors
        self.register_injector("date", date_injector, 
                              description="Full date and time description",
                              enabled=True)
        self.register_injector("time", time_injector,
                              description="Current time (HH:MM:SS)",
                              enabled=True)
        self.register_injector("short_date", short_date_injector,
                              description="Short date (YYYY-MM-DD)",
                              enabled=True)
        self.register_injector("timestamp", timestamp_injector,
                              description="ISO timestamp",
                              enabled=True)
        self.register_injector("user", user_injector,
                              description="Current username",
                              enabled=True)
        self.register_injector("system", system_injector,
                              description="System information",
                              enabled=True)
        self.register_injector("python_version", python_version_injector,
                              description="Python version",
                              enabled=True)
        self.register_injector("cwd", cwd_injector,
                              description="Current working directory",
                              enabled=True)
        self.register_injector("weekday", weekday_injector,
                              description="Day of the week",
                              enabled=True)
        self.register_injector("month", month_injector,
                              description="Current month name",
                              enabled=True)
        self.register_injector("year", year_injector,
                              description="Current year",
                              enabled=True)
    
    def register_injector(self, 
                         name: str, 
                         function: Callable[[], str],
                         description: str = "",
                         enabled: bool = True,
                         cacheable: bool = False) -> None:
        """
        Register a new injector function.
        
        Args:
            name (str): The placeholder name (without braces)
            function (Callable[[], str]): Function that returns the injection value
            description (str): Human-readable description of the injector
            enabled (bool): Whether this injector is enabled by default
            cacheable (bool): Whether to cache the result (useful for expensive operations)
        
        Example:
            def custom_injector():
                return "custom value"
            
            injector.register_injector("custom", custom_injector)
            # Now {custom} will be replaced with "custom value"
        """
        if cacheable and self._cache_enabled:
            # Wrap with LRU cache for expensive operations
            function = lru_cache(maxsize=1)(function)
        
        self._injectors[name] = {
            "function": function,
            "description": description,
            "enabled": enabled,
            "cacheable": cacheable
        }
    
    def unregister_injector(self, name: str) -> None:
        """
        Remove an injector from the registry.
        
        Args:
            name (str): The injector name to remove
        """
        if name in self._injectors:
            del self._injectors[name]
    
    def enable_injector(self, name: str) -> None:
        """
        Enable a specific injector.
        
        Args:
            name (str): The injector name to enable
        """
        if name in self._injectors:
            self._injectors[name]["enabled"] = True
    
    def disable_injector(self, name: str) -> None:
        """
        Disable a specific injector.
        
        Args:
            name (str): The injector name to disable
        """
        if name in self._injectors:
            self._injectors[name]["enabled"] = False
    
    def get_injectors(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all registered injectors.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary of injector information
        """
        return {
            name: {
                "description": info["description"],
                "enabled": info["enabled"],
                "cacheable": info["cacheable"]
            }
            for name, info in self._injectors.items()
        }
    
    def list_enabled_injectors(self) -> List[str]:
        """
        Get list of currently enabled injector names.
        
        Returns:
            List[str]: List of enabled injector names
        """
        return [name for name, info in self._injectors.items() if info["enabled"]]
    
    def detect_placeholders(self, text: str) -> List[str]:
        """
        Detect which registered placeholders are present in the text.
        
        Args:
            text (str): Text to scan for placeholders
        
        Returns:
            List[str]: List of detected placeholder names
        """
        detected = []
        for name in self._injectors:
            if f"{{{name}}}" in text:
                detected.append(name)
        return detected
    
    def inject(self, text: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Perform auto-injection on the given text.
        
        This method scans the text for registered placeholders and replaces them
        with computed values from the corresponding injector functions.
        
        Args:
            text (str): Text containing placeholders to inject
            context (Optional[Dict[str, Any]]): Additional context values that
                                               override injectors
        
        Returns:
            str: Text with injected values
        
        Example:
            text = "Hello {user}, today is {date}"
            result = injector.inject(text)
            # Result: "Hello john, today is The current date is '25 December 2024'..."
        """
        if not self.enabled:
            return text
        
        if context is None:
            context = {}
        
        result = text
        
        # Process each enabled injector
        for name, info in self._injectors.items():
            if not info["enabled"]:
                continue
            
            placeholder = f"{{{name}}}"
            
            # Skip if placeholder not in text
            if placeholder not in result:
                continue
            
            # Check if context provides an override
            if name in context:
                value = str(context[name])
            else:
                # Call the injector function
                try:
                    value = info["function"]()
                except Exception as e:
                    # If injection fails, leave placeholder as is
                    print(f"Warning: Injector '{name}' failed: {e}")
                    continue
            
            # Replace all occurrences
            result = result.replace(placeholder, value)
        
        return result
    
    def inject_selective(self, text: str, only: Optional[List[str]] = None, 
                        exclude: Optional[List[str]] = None,
                        context: Optional[Dict[str, Any]] = None) -> str:
        """
        Perform selective injection on specific placeholders.
        
        Args:
            text (str): Text containing placeholders
            only (Optional[List[str]]): Only inject these placeholders
            exclude (Optional[List[str]]): Exclude these placeholders from injection
            context (Optional[Dict[str, Any]]): Additional context values
        
        Returns:
            str: Text with selective injection applied
        """
        if not self.enabled:
            return text
        
        # Temporarily adjust enabled status
        original_states = {}
        
        if only is not None:
            # Disable all except specified
            for name in self._injectors:
                original_states[name] = self._injectors[name]["enabled"]
                self._injectors[name]["enabled"] = name in only
        elif exclude is not None:
            # Disable specified ones
            for name in exclude:
                if name in self._injectors:
                    original_states[name] = self._injectors[name]["enabled"]
                    self._injectors[name]["enabled"] = False
        
        try:
            # Perform injection with modified settings
            result = self.inject(text, context)
        finally:
            # Restore original states
            for name, state in original_states.items():
                self._injectors[name]["enabled"] = state
        
        return result
    
    def clear_cache(self):
        """Clear cached values for cacheable injectors."""
        for info in self._injectors.values():
            if info["cacheable"] and hasattr(info["function"], "cache_clear"):
                info["function"].cache_clear()
    
    def __call__(self, text: str, **kwargs) -> str:
        """
        Allow the injector to be called directly.
        
        Args:
            text (str): Text to inject
            **kwargs: Additional context values
        
        Returns:
            str: Injected text
        """
        return self.inject(text, context=kwargs)


# Global default injector instance
_default_injector = None


def get_default_injector() -> AutoInjector:
    """
    Get or create the default AutoInjector instance.
    
    Returns:
        AutoInjector: The default injector instance
    """
    global _default_injector
    if _default_injector is None:
        _default_injector = AutoInjector()
    return _default_injector


def inject(text: str, **kwargs) -> str:
    """
    Convenience function to inject using the default injector.
    
    Args:
        text (str): Text to inject
        **kwargs: Context values
    
    Returns:
        str: Injected text
    """
    return get_default_injector().inject(text, context=kwargs)


def register_global_injector(name: str, function: Callable[[], str], **kwargs) -> None:
    """
    Register an injector with the global default injector.
    
    Args:
        name (str): Injector name
        function (Callable[[], str]): Injector function
        **kwargs: Additional arguments for register_injector
    """
    get_default_injector().register_injector(name, function, **kwargs)
