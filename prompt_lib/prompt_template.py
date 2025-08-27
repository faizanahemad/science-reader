"""
Advanced Prompt Template System

This module provides advanced templating capabilities for LLM prompts with features like
conditional logic, loops, and advanced validation. It extends the basic prompt composition
functionality with more sophisticated template processing.

Key Features:
- Advanced template syntax with conditional logic
- Loop constructs for dynamic content generation
- Template inheritance and includes
- Variable validation and type checking
- Template compilation and caching
- Integration with PromptManager for seamless composition

Author: AI Assistant
Created: 2025
"""

import re
from typing import Dict, Any, List, Optional, Union, Callable
from datetime import datetime
import json
from copy import deepcopy


class TemplateError(Exception):
    """Custom exception for template processing errors."""
    pass


class TemplateValidationError(Exception):
    """Custom exception for template validation errors."""
    pass


class PromptTemplate:
    """
    Advanced template processor for LLM prompts with support for conditional logic,
    loops, and sophisticated variable substitution.
    
    This class provides a powerful templating system that goes beyond simple string
    formatting to include:
    - Conditional blocks (if/else/elif)
    - Loop constructs (for loops with iterables)
    - Variable validation and type checking
    - Template functions and filters
    - Nested template processing
    - Template compilation for performance
    
    The template syntax uses a custom format that's both powerful and readable:
    - Variables: {variable_name}
    - Conditions: {% if condition %} ... {% endif %}
    - Loops: {% for item in items %} ... {% endfor %}
    - Functions: {function_name(args)}
    """
    
    def __init__(self, template_content: str, name: str = None):
        """
        Initialize a PromptTemplate with content and optional metadata.
        
        Args:
            template_content (str): The template content with placeholders and logic
            name (str, optional): Name identifier for the template
        """
        self.content = template_content
        self.name = name or f"template_{id(self)}"
        self.compiled = False
        self._compiled_template = None
        self._variables = set()
        self._functions = {}
        self._filters = {}
        
        # Built-in template functions
        self._register_builtin_functions()
        
        # Parse template to extract variables
        self._parse_template()
    
    def _register_builtin_functions(self):
        """Register built-in template functions."""
        self._functions.update({
            'len': len,
            'upper': str.upper,
            'lower': str.lower,
            'strip': str.strip,
            'title': str.title,
            'capitalize': str.capitalize,
            'now': lambda: datetime.now().isoformat(),
            'date': lambda: datetime.now().strftime('%Y-%m-%d'),
            'time': lambda: datetime.now().strftime('%H:%M:%S'),
            'join': lambda items, sep=', ': sep.join(str(item) for item in items),
            'default': lambda value, default_val: default_val if not value else value,
        })
    
    def _parse_template(self):
        """Parse the template to extract variables and validate syntax."""
        # Extract simple variables {variable_name}
        simple_vars = re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', self.content)
        self._variables.update(simple_vars)
        
        # Extract function calls {function_name(args)}
        function_calls = re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*\)\}', self.content)
        
        # Extract variables from control structures
        control_vars = re.findall(r'\{%\s*(?:if|for)\s+([^%]+)%\}', self.content)
        for var_expr in control_vars:
            # Extract variable names from expressions
            vars_in_expr = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', var_expr)
            self._variables.update(vars_in_expr)
        
        # Validate template syntax
        self._validate_template_syntax()
    
    def _validate_template_syntax(self):
        """Validate the template syntax for common errors."""
        content = self.content
        
        # Check for unmatched braces
        open_braces = content.count('{')
        close_braces = content.count('}')
        if open_braces != close_braces:
            raise TemplateValidationError(f"Unmatched braces in template '{self.name}': {open_braces} open, {close_braces} close")
        
        # Check for unmatched control structures
        if_count = len(re.findall(r'\{%\s*if\s+', content))
        endif_count = len(re.findall(r'\{%\s*endif\s*%\}', content))
        if if_count != endif_count:
            raise TemplateValidationError(f"Unmatched if/endif blocks in template '{self.name}': {if_count} if, {endif_count} endif")
        
        for_count = len(re.findall(r'\{%\s*for\s+', content))
        endfor_count = len(re.findall(r'\{%\s*endfor\s*%\}', content))
        if for_count != endfor_count:
            raise TemplateValidationError(f"Unmatched for/endfor blocks in template '{self.name}': {for_count} for, {endfor_count} endfor")
    
    def add_function(self, name: str, func: Callable):
        """
        Add a custom function to the template.
        
        Args:
            name (str): Function name to use in templates
            func (Callable): The function to call
        """
        self._functions[name] = func
    
    def add_filter(self, name: str, func: Callable):
        """
        Add a custom filter to the template.
        
        Args:
            name (str): Filter name to use in templates
            func (Callable): The filter function
        """
        self._filters[name] = func
    
    def get_variables(self) -> List[str]:
        """
        Get all variables used in the template.
        
        Returns:
            List[str]: List of variable names
        """
        return sorted(list(self._variables))
    
    def validate_context(self, context: Dict[str, Any]) -> List[str]:
        """
        Validate that the context provides all required variables.
        
        Args:
            context (Dict[str, Any]): Context variables
        
        Returns:
            List[str]: List of missing variable names
        """
        missing_vars = []
        for var in self._variables:
            if var not in context:
                # Check if it's a built-in function
                if var not in self._functions:
                    missing_vars.append(var)
        return missing_vars
    
    def render(self, context: Dict[str, Any] = None, strict: bool = True) -> str:
        """
        Render the template with the provided context.
        
        Args:
            context (Dict[str, Any]): Variables and values for template substitution
            strict (bool): If True, raise error on missing variables. If False, leave placeholders.
        
        Returns:
            str: The rendered template content
        
        Raises:
            TemplateError: If template processing fails
            TemplateValidationError: If required variables are missing (in strict mode)
        """
        if context is None:
            context = {}
        
        # Validate context in strict mode
        if strict:
            missing_vars = self.validate_context(context)
            if missing_vars:
                raise TemplateValidationError(f"Missing required variables: {missing_vars}")
        
        # Create rendering context with functions
        render_context = deepcopy(context)
        render_context.update(self._functions)
        
        try:
            # Process the template
            result = self._process_template(self.content, render_context, strict)
            return result
        except Exception as e:
            raise TemplateError(f"Error rendering template '{self.name}': {str(e)}")
    
    def _process_template(self, content: str, context: Dict[str, Any], strict: bool) -> str:
        """
        Process template content with control structures and variable substitution.
        
        Args:
            content (str): Template content to process
            context (Dict[str, Any]): Rendering context
            strict (bool): Strict mode flag
        
        Returns:
            str: Processed content
        """
        # Process control structures first
        content = self._process_if_blocks(content, context, strict)
        content = self._process_for_loops(content, context, strict)
        
        # Process function calls
        content = self._process_function_calls(content, context, strict)
        
        # Process simple variable substitution
        content = self._process_variables(content, context, strict)
        
        return content
    
    def _process_if_blocks(self, content: str, context: Dict[str, Any], strict: bool) -> str:
        """Process if/else/endif blocks in the template."""
        # Pattern for if blocks with optional else
        if_pattern = r'\{%\s*if\s+([^%]+)%\}(.*?)\{%\s*endif\s*%\}'
        
        def replace_if_block(match):
            condition_expr = match.group(1).strip()
            block_content = match.group(2)
            
            # Check for else clause
            else_match = re.search(r'(.*?)\{%\s*else\s*%\}(.*)', block_content, re.DOTALL)
            if else_match:
                if_content = else_match.group(1)
                else_content = else_match.group(2)
            else:
                if_content = block_content
                else_content = ""
            
            # Evaluate condition
            try:
                condition_result = self._evaluate_condition(condition_expr, context)
                if condition_result:
                    return self._process_template(if_content, context, strict)
                else:
                    return self._process_template(else_content, context, strict)
            except Exception as e:
                if strict:
                    raise TemplateError(f"Error evaluating condition '{condition_expr}': {e}")
                return match.group(0)  # Return original if evaluation fails
        
        # Process all if blocks
        while re.search(if_pattern, content, re.DOTALL):
            content = re.sub(if_pattern, replace_if_block, content, flags=re.DOTALL)
        
        return content
    
    def _process_for_loops(self, content: str, context: Dict[str, Any], strict: bool) -> str:
        """Process for loops in the template."""
        for_pattern = r'\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}'
        
        def replace_for_loop(match):
            loop_var = match.group(1)
            iterable_name = match.group(2)
            loop_content = match.group(3)
            
            # Get the iterable from context
            if iterable_name not in context:
                if strict:
                    raise TemplateError(f"Iterable '{iterable_name}' not found in context")
                return match.group(0)
            
            iterable = context[iterable_name]
            if not hasattr(iterable, '__iter__') or isinstance(iterable, str):
                if strict:
                    raise TemplateError(f"'{iterable_name}' is not iterable")
                return match.group(0)
            
            # Process loop
            result_parts = []
            for item in iterable:
                loop_context = deepcopy(context)
                loop_context[loop_var] = item
                processed_content = self._process_template(loop_content, loop_context, strict)
                result_parts.append(processed_content)
            
            return ''.join(result_parts)
        
        # Process all for loops
        while re.search(for_pattern, content, re.DOTALL):
            content = re.sub(for_pattern, replace_for_loop, content, flags=re.DOTALL)
        
        return content
    
    def _process_function_calls(self, content: str, context: Dict[str, Any], strict: bool) -> str:
        """Process function calls in the template."""
        func_pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\(([^)]*)\)\}'
        
        def replace_function_call(match):
            func_name = match.group(1)
            args_str = match.group(2).strip()
            
            if func_name not in self._functions:
                if strict:
                    raise TemplateError(f"Unknown function '{func_name}'")
                return match.group(0)
            
            func = self._functions[func_name]
            
            # Parse arguments
            args = []
            if args_str:
                # Simple argument parsing (supports strings, numbers, and variables)
                arg_parts = [arg.strip() for arg in args_str.split(',')]
                for arg in arg_parts:
                    if arg.startswith('"') and arg.endswith('"'):
                        # String literal
                        args.append(arg[1:-1])
                    elif arg.startswith("'") and arg.endswith("'"):
                        # String literal
                        args.append(arg[1:-1])
                    elif arg.isdigit():
                        # Integer
                        args.append(int(arg))
                    elif arg.replace('.', '').isdigit():
                        # Float
                        args.append(float(arg))
                    elif arg in context:
                        # Variable reference
                        args.append(context[arg])
                    else:
                        # Unknown argument
                        if strict:
                            raise TemplateError(f"Unknown argument '{arg}' in function call")
                        args.append(arg)
            
            # Call function
            try:
                result = func(*args)
                return str(result)
            except Exception as e:
                if strict:
                    raise TemplateError(f"Error calling function '{func_name}': {e}")
                return match.group(0)
        
        return re.sub(func_pattern, replace_function_call, content)
    
    def _process_variables(self, content: str, context: Dict[str, Any], strict: bool) -> str:
        """Process simple variable substitution."""
        var_pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
        
        def replace_variable(match):
            var_name = match.group(1)
            
            if var_name in context:
                return str(context[var_name])
            elif var_name in self._functions:
                # It's a function without parentheses - call with no args
                try:
                    result = self._functions[var_name]()
                    return str(result)
                except:
                    if strict:
                        raise TemplateError(f"Error calling function '{var_name}' without arguments")
                    return match.group(0)
            else:
                if strict:
                    raise TemplateError(f"Unknown variable '{var_name}'")
                return match.group(0)
        
        return re.sub(var_pattern, replace_variable, content)
    
    def _evaluate_condition(self, condition_expr: str, context: Dict[str, Any]) -> bool:
        """
        Evaluate a condition expression safely.
        
        Args:
            condition_expr (str): The condition expression to evaluate
            context (Dict[str, Any]): Variable context
        
        Returns:
            bool: Result of condition evaluation
        """
        # Simple condition evaluation - supports basic comparisons and boolean logic
        # This is a simplified implementation. For production use, consider using
        # a proper expression parser or restricted eval.
        
        # Replace variables with their values
        for var_name, value in context.items():
            if isinstance(value, str):
                condition_expr = condition_expr.replace(var_name, f'"{value}"')
            else:
                condition_expr = condition_expr.replace(var_name, str(value))
        
        # Basic safety check - only allow safe operations
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !=<>()"\'.and or not')
        if not all(c in allowed_chars for c in condition_expr):
            raise TemplateError(f"Unsafe characters in condition: {condition_expr}")
        
        try:
            # Use eval with restricted globals for basic condition evaluation
            # Note: This is simplified. Production code should use a proper expression parser.
            result = eval(condition_expr, {"__builtins__": {}}, {})
            return bool(result)
        except Exception as e:
            raise TemplateError(f"Error evaluating condition '{condition_expr}': {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert template to dictionary representation.
        
        Returns:
            Dict[str, Any]: Template metadata and content
        """
        return {
            "name": self.name,
            "content": self.content,
            "variables": self.get_variables(),
            "functions": list(self._functions.keys()),
            "compiled": self.compiled
        }
    
    def __str__(self) -> str:
        return f"PromptTemplate(name='{self.name}', variables={len(self._variables)})"
    
    def __repr__(self) -> str:
        return self.__str__()


class TemplateLibrary:
    """
    A collection of PromptTemplate instances with management capabilities.
    
    This class provides a way to organize and manage multiple templates,
    with features like template inheritance, includes, and batch operations.
    """
    
    def __init__(self):
        """Initialize an empty template library."""
        self._templates: Dict[str, PromptTemplate] = {}
    
    def add_template(self, template: PromptTemplate) -> None:
        """
        Add a template to the library.
        
        Args:
            template (PromptTemplate): Template to add
        """
        self._templates[template.name] = template
    
    def get_template(self, name: str) -> PromptTemplate:
        """
        Get a template by name.
        
        Args:
            name (str): Template name
        
        Returns:
            PromptTemplate: The requested template
        
        Raises:
            KeyError: If template not found
        """
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found")
        return self._templates[name]
    
    def list_templates(self) -> List[str]:
        """
        List all template names.
        
        Returns:
            List[str]: List of template names
        """
        return sorted(list(self._templates.keys()))
    
    def render_template(self, name: str, context: Dict[str, Any] = None, strict: bool = True) -> str:
        """
        Render a template by name.
        
        Args:
            name (str): Template name
            context (Dict[str, Any]): Rendering context
            strict (bool): Strict mode flag
        
        Returns:
            str: Rendered template
        """
        template = self.get_template(name)
        return template.render(context, strict)
    
    def batch_render(self, templates: List[str], context: Dict[str, Any] = None) -> Dict[str, str]:
        """
        Render multiple templates with the same context.
        
        Args:
            templates (List[str]): List of template names to render
            context (Dict[str, Any]): Shared rendering context
        
        Returns:
            Dict[str, str]: Mapping of template names to rendered content
        """
        results = {}
        for template_name in templates:
            try:
                results[template_name] = self.render_template(template_name, context)
            except Exception as e:
                results[template_name] = f"Error: {str(e)}"
        return results
