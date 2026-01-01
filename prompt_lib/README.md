# Prompt Library

A comprehensive system for managing LLM prompts with dictionary-like access, automatic composition, and advanced templating features.

## Features

- 🎯 **Dictionary-like Interface**: Use prompts like a Python dictionary
- 🔄 **Automatic Composition**: Prompts can reference other prompts automatically
- 💾 **Persistent Storage**: JSON-based storage with auto-save
- 🔍 **Search & Analytics**: Find and analyze your prompts
- 📝 **Advanced Templates**: Conditional logic, loops, and functions
- 🛠️ **Migration Tools**: Import from existing prompt systems
- 🧪 **Comprehensive Testing**: Full test suite included

## Quick Start

```python
from prompt_lib import create_wrapped_manager

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
```

## Key Classes

### WrappedManager

The main interface - provides dictionary-like access with automatic composition:

```python
from prompt_lib import WrappedManager, PromptManager

# Create from existing PromptManager
base_manager = PromptManager("prompts.json")
wrapped = WrappedManager(base_manager)

# Or use the convenience function
wrapped = create_wrapped_manager("prompts.json")

# Dictionary operations
wrapped["prompt_name"] = "Prompt content with {placeholder}"
content = wrapped["prompt_name"]  # Automatically composed
del wrapped["prompt_name"]
"prompt_name" in wrapped  # True/False

# Advanced operations
wrapped.compose("prompt_name", placeholder="value")
wrapped.search("keyword")
wrapped.analyze()  # Usage analytics
```

### PromptManager

The underlying storage and management system:

```python
from prompt_lib import PromptManager

manager = PromptManager("prompts.json")

# Store prompts with metadata
manager.store_prompt(
    name="example",
    content="Example prompt with {variable}",
    description="An example prompt",
    category="examples",
    tags=["demo", "test"]
)

# Compose prompts
result = manager.compose_prompt("example", variable="value")

# Search and list
prompts = manager.search_prompts("keyword")
by_category = manager.list_prompts(category="examples")
```

### PromptTemplate

Advanced templating with conditional logic:

```python
from prompt_lib import PromptTemplate

template = PromptTemplate("""
{% if urgent %}URGENT: {% endif %}
Hello {name},
{% for item in items %}
- {item}
{% endfor %}
Best regards
""")

result = template.render({
    "urgent": True,
    "name": "Alice", 
    "items": ["Task 1", "Task 2"]
})
```

## Real-World Example

```python
from prompt_lib import create_wrapped_manager

# Create email template system
email_manager = create_wrapped_manager("email_templates.json")

# Define reusable components
email_manager["header"] = "Subject: {subject}\nFrom: {sender}\nTo: {recipient}\n"
email_manager["greeting"] = "Dear {recipient_name},"
email_manager["closing"] = "Best regards,\n{sender_name}"
email_manager["signature"] = "{sender_name}\n{title}\n{company}"

# Compose complete email template
email_manager["professional_email"] = """{header}

{greeting}

{body}

{closing}
{signature}"""

# Use the template
email = email_manager.compose("professional_email",
    subject="Project Update",
    sender="john@company.com",
    recipient="alice@company.com", 
    recipient_name="Alice",
    sender_name="John Smith",
    title="Project Manager",
    company="Tech Corp",
    body="Here's the latest update on our project..."
)
```

## Migration from Existing Systems

```python
from prompt_lib import migrate_from_prompts_py, create_wrapped_manager

# Migrate from existing prompts.py file
manager = create_wrapped_manager("new_prompts.json")
report = migrate_from_prompts_py("old_prompts.py", manager.manager)

print(f"Migrated {report['successfully_imported']} prompts")
```

## Testing

Run the comprehensive test suite:

```bash
python -m prompt_lib.test_wrapped_manager
```

Run the demo:

```bash
python -m prompt_lib.demo
```

## File Structure

```
prompt_lib/
├── __init__.py              # Main package interface
├── prompt_manager.py        # Core PromptManager class
├── wrapped_manager.py       # Dictionary-like wrapper
├── prompt_template.py       # Advanced templating
├── utils.py                 # Utility functions
├── test_wrapped_manager.py  # Test suite
├── demo.py                  # Demonstration script
└── README.md               # This file
```

## API Reference

### WrappedManager Methods

- `manager[key]` - Get composed prompt
- `manager[key] = value` - Store prompt (auto-save)
- `del manager[key]` - Delete prompt
- `key in manager` - Check existence
- `len(manager)` - Number of prompts
- `manager.keys()` - All prompt names
- `manager.values()` - All prompt contents (composed)
- `manager.items()` - Name-content pairs
- `manager.get_raw(key)` - Get without composition
- `manager.compose(key, **context)` - Compose with context
- `manager.search(query)` - Search prompts
- `manager.analyze()` - Usage analytics

### Utility Functions

- `discover_prompts_in_file(path)` - Find prompts in Python files
- `migrate_from_prompts_py(path, manager)` - Migrate existing prompts
- `validate_prompt_content(content)` - Validate prompt syntax
- `backup_prompts(manager, path)` - Create backup
- `restore_prompts(manager, path)` - Restore from backup

## Advanced Features

### Auto-Composition Control

```python
manager = create_wrapped_manager("prompts.json")
manager.auto_compose = False  # Disable automatic composition
raw_content = manager["prompt_name"]  # Returns raw content
manager.auto_compose = True   # Re-enable
```

### Prompt Dependencies

```python
from prompt_lib import find_prompt_dependencies

deps = find_prompt_dependencies("main_prompt", manager.manager)
print(f"Dependencies: {deps['dependencies']}")
print(f"Dependents: {deps['dependents']}")
```

### Optimization

```python
optimization = manager.optimize()
print(f"Duplicate prompts: {len(optimization['duplicate_content'])}")
print(f"Unused prompts: {len(optimization['unused_prompts'])}")
```

## Error Handling

The library provides specific exceptions for different error conditions:

- `PromptNotFoundError` - Prompt doesn't exist
- `PromptValidationError` - Invalid prompt content or structure
- `TemplateError` - Template processing error
- `TemplateValidationError` - Template syntax error

## License

This library is created for research and development purposes.

## Contributing

This is a research project. Feel free to extend and modify as needed for your use case.
