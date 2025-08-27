"""
Utility functions for the Prompt Library system.

This module provides helper functions for prompt management, validation, discovery,
and integration with the broader prompt ecosystem. It includes utilities for
working with existing prompt systems and migration tools.

Key Features:
- Prompt validation and linting
- Discovery of prompts in existing codebases
- Migration tools for existing prompt systems
- Integration helpers for common LLM frameworks
- Prompt analytics and statistics
- Backup and restore functionality

Author: AI Assistant
Created: 2025
"""

import os
import re
import json
from typing import Dict, Any, List, Optional, Tuple, Set
from pathlib import Path
import hashlib
from datetime import datetime
from .prompt_manager import PromptManager, PromptValidationError, PromptNotFoundError
from .prompt_template import PromptTemplate, TemplateError


def discover_prompts_in_file(file_path: str, patterns: List[str] = None) -> List[Dict[str, Any]]:
    """
    Discover prompt-like strings in a Python file.
    
    This function scans Python files for string literals that appear to be prompts,
    based on common patterns like multi-line strings, strings with placeholders,
    and strings assigned to prompt-related variable names.
    
    Args:
        file_path (str): Path to the Python file to scan
        patterns (List[str], optional): Additional regex patterns to match prompts
    
    Returns:
        List[Dict[str, Any]]: List of discovered prompts with metadata
    """
    if patterns is None:
        patterns = [
            r'(\w*prompt\w*)\s*=\s*[rf]?["\']([^"\']+)["\']',  # prompt variable assignments
            r'(\w*template\w*)\s*=\s*[rf]?["\']([^"\']+)["\']',  # template assignments
            r'[rf]?"""([^"]+)"""',  # triple-quoted strings
            r'[rf]?\'\'\'([^\']+)\'\'\'',  # triple-quoted strings with single quotes
        ]
    
    discovered_prompts = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract prompts using patterns
        for i, pattern in enumerate(patterns):
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                if len(match.groups()) >= 2:
                    var_name = match.group(1)
                    prompt_content = match.group(2)
                else:
                    var_name = f"discovered_prompt_{i}_{len(discovered_prompts)}"
                    prompt_content = match.group(1)
                
                # Skip very short strings
                if len(prompt_content.strip()) < 20:
                    continue
                
                # Calculate line number
                line_num = content[:match.start()].count('\n') + 1
                
                discovered_prompts.append({
                    "name": var_name,
                    "content": prompt_content.strip(),
                    "file_path": file_path,
                    "line_number": line_num,
                    "pattern_index": i,
                    "discovered_at": datetime.now().isoformat()
                })
    
    except Exception as e:
        print(f"Error scanning file {file_path}: {e}")
    
    return discovered_prompts


def discover_prompts_in_directory(directory: str, 
                                 file_extensions: List[str] = None,
                                 exclude_dirs: List[str] = None) -> List[Dict[str, Any]]:
    """
    Recursively discover prompts in a directory.
    
    Args:
        directory (str): Directory to scan
        file_extensions (List[str]): File extensions to scan (default: ['.py'])
        exclude_dirs (List[str]): Directory names to exclude (default: common exclusions)
    
    Returns:
        List[Dict[str, Any]]: List of all discovered prompts
    """
    if file_extensions is None:
        file_extensions = ['.py']
    
    if exclude_dirs is None:
        exclude_dirs = ['__pycache__', '.git', '.venv', 'venv', 'node_modules', '.pytest_cache']
    
    all_prompts = []
    
    for root, dirs, files in os.walk(directory):
        # Remove excluded directories from dirs list to avoid traversing them
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if any(file.endswith(ext) for ext in file_extensions):
                file_path = os.path.join(root, file)
                prompts = discover_prompts_in_file(file_path)
                all_prompts.extend(prompts)
    
    return all_prompts


def migrate_from_prompts_py(prompts_py_path: str, prompt_manager: PromptManager) -> Dict[str, Any]:
    """
    Migrate prompts from an existing prompts.py file to the PromptManager.
    
    This function analyzes an existing prompts.py file (like the one in your codebase)
    and extracts prompts to import into the new prompt management system.
    
    Args:
        prompts_py_path (str): Path to the existing prompts.py file
        prompt_manager (PromptManager): PromptManager instance to import into
    
    Returns:
        Dict[str, Any]: Migration report with statistics and any errors
    """
    migration_report = {
        "total_discovered": 0,
        "successfully_imported": 0,
        "errors": [],
        "imported_prompts": [],
        "skipped_prompts": []
    }
    
    try:
        # Discover prompts in the file
        discovered_prompts = discover_prompts_in_file(prompts_py_path)
        migration_report["total_discovered"] = len(discovered_prompts)
        
        for prompt_data in discovered_prompts:
            try:
                # Clean up the prompt name
                name = prompt_data["name"]
                if not name or name.startswith("discovered_prompt_"):
                    # Generate a better name based on content
                    content_preview = prompt_data["content"][:50].replace('\n', ' ')
                    name = f"migrated_prompt_{hashlib.md5(content_preview.encode()).hexdigest()[:8]}"
                
                # Store the prompt
                prompt_manager.store_prompt(
                    name=name,
                    content=prompt_data["content"],
                    description=f"Migrated from {prompts_py_path} at line {prompt_data['line_number']}",
                    category="migrated",
                    tags=["migrated", "legacy"],
                    metadata={
                        "source_file": prompt_data["file_path"],
                        "source_line": prompt_data["line_number"],
                        "migration_date": datetime.now().isoformat(),
                        "original_name": prompt_data["name"]
                    }
                )
                
                migration_report["successfully_imported"] += 1
                migration_report["imported_prompts"].append(name)
                
            except Exception as e:
                error_msg = f"Failed to import prompt '{prompt_data['name']}': {str(e)}"
                migration_report["errors"].append(error_msg)
                migration_report["skipped_prompts"].append(prompt_data["name"])
    
    except Exception as e:
        migration_report["errors"].append(f"Failed to process file {prompts_py_path}: {str(e)}")
    
    return migration_report


def validate_prompt_content(content: str) -> Dict[str, Any]:
    """
    Validate prompt content and provide suggestions for improvement.
    
    Args:
        content (str): Prompt content to validate
    
    Returns:
        Dict[str, Any]: Validation results with suggestions
    """
    validation_result = {
        "is_valid": True,
        "warnings": [],
        "suggestions": [],
        "metrics": {},
        "placeholders": []
    }
    
    # Basic metrics
    validation_result["metrics"] = {
        "character_count": len(content),
        "word_count": len(content.split()),
        "line_count": content.count('\n') + 1,
        "placeholder_count": len(re.findall(r'\{[^}]+\}', content))
    }
    
    # Find placeholders
    placeholders = re.findall(r'\{([^}]+)\}', content)
    validation_result["placeholders"] = list(set(placeholders))
    
    # Validation checks
    if len(content.strip()) < 10:
        validation_result["warnings"].append("Prompt is very short (less than 10 characters)")
    
    if len(content) > 10000:
        validation_result["warnings"].append("Prompt is very long (over 10,000 characters)")
    
    # Check for unmatched braces
    open_braces = content.count('{')
    close_braces = content.count('}')
    if open_braces != close_braces:
        validation_result["is_valid"] = False
        validation_result["warnings"].append(f"Unmatched braces: {open_braces} open, {close_braces} close")
    
    # Check for common issues
    if '{{' in content or '}}' in content:
        validation_result["suggestions"].append("Double braces found - consider if this is intentional for literal braces")
    
    if re.search(r'\{\s+\w+\s+\}', content):
        validation_result["suggestions"].append("Placeholders with spaces found - consider removing spaces")
    
    # Check for potentially problematic patterns
    if re.search(r'\{[^}]*\{[^}]*\}[^}]*\}', content):
        validation_result["warnings"].append("Nested braces detected - this may cause formatting issues")
    
    return validation_result


def analyze_prompt_usage(prompt_manager: PromptManager) -> Dict[str, Any]:
    """
    Analyze prompt usage patterns and provide insights.
    
    Args:
        prompt_manager (PromptManager): PromptManager instance to analyze
    
    Returns:
        Dict[str, Any]: Usage analysis and statistics
    """
    all_prompts = prompt_manager.get_all_prompts()
    
    analysis = {
        "total_prompts": len(all_prompts),
        "categories": {},
        "tags": {},
        "average_length": 0,
        "placeholder_usage": {},
        "creation_timeline": {},
        "most_complex_prompts": [],
        "unused_prompts": [],
        "recommendations": []
    }
    
    if not all_prompts:
        return analysis
    
    # Analyze categories and tags
    total_length = 0
    all_placeholders = []
    
    for name, prompt_data in all_prompts.items():
        content = prompt_data.get("content", "")
        category = prompt_data.get("category", "uncategorized")
        tags = prompt_data.get("tags", [])
        created_at = prompt_data.get("created_at", "")
        
        # Category analysis
        analysis["categories"][category] = analysis["categories"].get(category, 0) + 1
        
        # Tag analysis
        for tag in tags:
            analysis["tags"][tag] = analysis["tags"].get(tag, 0) + 1
        
        # Length analysis
        total_length += len(content)
        
        # Placeholder analysis
        placeholders = re.findall(r'\{([^}]+)\}', content)
        all_placeholders.extend(placeholders)
        
        # Timeline analysis
        if created_at:
            try:
                date = datetime.fromisoformat(created_at).date().isoformat()
                analysis["creation_timeline"][date] = analysis["creation_timeline"].get(date, 0) + 1
            except:
                pass
        
        # Complexity analysis (based on length and placeholder count)
        complexity_score = len(content) + len(placeholders) * 10
        analysis["most_complex_prompts"].append({
            "name": name,
            "complexity_score": complexity_score,
            "length": len(content),
            "placeholder_count": len(placeholders)
        })
    
    # Calculate averages and statistics
    analysis["average_length"] = total_length // len(all_prompts) if all_prompts else 0
    
    # Placeholder usage frequency
    for placeholder in set(all_placeholders):
        analysis["placeholder_usage"][placeholder] = all_placeholders.count(placeholder)
    
    # Sort most complex prompts
    analysis["most_complex_prompts"].sort(key=lambda x: x["complexity_score"], reverse=True)
    analysis["most_complex_prompts"] = analysis["most_complex_prompts"][:10]  # Top 10
    
    # Generate recommendations
    if analysis["total_prompts"] > 20 and len(analysis["categories"]) < 3:
        analysis["recommendations"].append("Consider organizing prompts into more categories")
    
    if analysis["average_length"] > 1000:
        analysis["recommendations"].append("Some prompts are quite long - consider breaking them into smaller, composable parts")
    
    if len(analysis["tags"]) < analysis["total_prompts"] // 5:
        analysis["recommendations"].append("Consider adding more tags to improve prompt discoverability")
    
    return analysis


def backup_prompts(prompt_manager: PromptManager, backup_path: str) -> bool:
    """
    Create a backup of all prompts.
    
    Args:
        prompt_manager (PromptManager): PromptManager instance
        backup_path (str): Path for the backup file
    
    Returns:
        bool: True if backup was successful
    """
    try:
        all_prompts = prompt_manager.get_all_prompts()
        backup_data = {
            "backup_created": datetime.now().isoformat(),
            "total_prompts": len(all_prompts),
            "prompts": all_prompts
        }
        
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully backed up {len(all_prompts)} prompts to {backup_path}")
        return True
    
    except Exception as e:
        print(f"Backup failed: {e}")
        return False


def restore_prompts(prompt_manager: PromptManager, backup_path: str, merge: bool = True) -> bool:
    """
    Restore prompts from a backup file.
    
    Args:
        prompt_manager (PromptManager): PromptManager instance
        backup_path (str): Path to the backup file
        merge (bool): If True, merge with existing prompts. If False, replace all.
    
    Returns:
        bool: True if restore was successful
    """
    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
        
        if "prompts" not in backup_data:
            print("Invalid backup file format")
            return False
        
        prompts_data = backup_data["prompts"]
        
        if not merge:
            # Clear existing prompts (this would need to be implemented in PromptManager)
            print("Warning: Full restore not implemented - using merge mode")
        
        # Restore each prompt
        restored_count = 0
        for name, prompt_data in prompts_data.items():
            try:
                prompt_manager.store_prompt(
                    name=name,
                    content=prompt_data.get("content", ""),
                    description=prompt_data.get("description", ""),
                    category=prompt_data.get("category", "general"),
                    tags=prompt_data.get("tags", []),
                    metadata=prompt_data.get("metadata", {})
                )
                restored_count += 1
            except Exception as e:
                print(f"Failed to restore prompt '{name}': {e}")
        
        print(f"Successfully restored {restored_count} prompts from {backup_path}")
        return True
    
    except Exception as e:
        print(f"Restore failed: {e}")
        return False


def create_prompt_from_template(template_content: str, 
                               name: str,
                               context: Dict[str, Any],
                               prompt_manager: PromptManager) -> str:
    """
    Create a new prompt by rendering a template and storing it.
    
    Args:
        template_content (str): Template content with placeholders
        name (str): Name for the new prompt
        context (Dict[str, Any]): Context for template rendering
        prompt_manager (PromptManager): PromptManager to store the result
    
    Returns:
        str: The rendered prompt content
    """
    template = PromptTemplate(template_content, name=f"temp_{name}")
    rendered_content = template.render(context)
    
    prompt_manager.store_prompt(
        name=name,
        content=rendered_content,
        description=f"Generated from template",
        category="generated",
        tags=["generated", "template"],
        metadata={
            "template_content": template_content,
            "template_context": context,
            "generated_at": datetime.now().isoformat()
        }
    )
    
    return rendered_content


def find_prompt_dependencies(prompt_name: str, prompt_manager: PromptManager) -> Dict[str, List[str]]:
    """
    Find dependencies for a prompt (what other prompts it references).
    
    Args:
        prompt_name (str): Name of the prompt to analyze
        prompt_manager (PromptManager): PromptManager instance
    
    Returns:
        Dict[str, List[str]]: Dependencies and dependents
    """
    try:
        prompt_data = prompt_manager.get_prompt(prompt_name)
        content = prompt_data["content"]
    except PromptNotFoundError:
        return {"dependencies": [], "dependents": [], "error": f"Prompt '{prompt_name}' not found"}
    
    # Find placeholders in the prompt
    placeholders = re.findall(r'\{([^}]+)\}', content)
    
    # Check which placeholders are actually other prompts
    all_prompts = prompt_manager.get_all_prompts()
    dependencies = [p for p in placeholders if p in all_prompts]
    
    # Find prompts that depend on this one
    dependents = []
    for name, prompt_data in all_prompts.items():
        if name != prompt_name:
            other_content = prompt_data["content"]
            if f"{{{prompt_name}}}" in other_content:
                dependents.append(name)
    
    return {
        "dependencies": dependencies,
        "dependents": dependents,
        "all_placeholders": placeholders
    }


def optimize_prompt_library(prompt_manager: PromptManager) -> Dict[str, Any]:
    """
    Analyze the prompt library and suggest optimizations.
    
    Args:
        prompt_manager (PromptManager): PromptManager instance
    
    Returns:
        Dict[str, Any]: Optimization suggestions and analysis
    """
    all_prompts = prompt_manager.get_all_prompts()
    
    optimization_report = {
        "duplicate_content": [],
        "unused_prompts": [],
        "overly_complex_prompts": [],
        "missing_dependencies": [],
        "circular_dependencies": [],
        "optimization_suggestions": []
    }
    
    # Find duplicate content
    content_hashes = {}
    for name, prompt_data in all_prompts.items():
        content = prompt_data["content"]
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        if content_hash in content_hashes:
            optimization_report["duplicate_content"].append({
                "prompts": [content_hashes[content_hash], name],
                "hash": content_hash
            })
        else:
            content_hashes[content_hash] = name
    
    # Find unused prompts and missing dependencies
    all_prompt_names = set(all_prompts.keys())
    referenced_prompts = set()
    
    for name, prompt_data in all_prompts.items():
        content = prompt_data["content"]
        placeholders = re.findall(r'\{([^}]+)\}', content)
        
        for placeholder in placeholders:
            if placeholder in all_prompt_names:
                referenced_prompts.add(placeholder)
            else:
                # Check if it looks like a prompt reference but doesn't exist
                if placeholder.endswith('_prompt') or placeholder.startswith('prompt_'):
                    optimization_report["missing_dependencies"].append({
                        "prompt": name,
                        "missing_reference": placeholder
                    })
    
    # Find unused prompts
    optimization_report["unused_prompts"] = list(all_prompt_names - referenced_prompts)
    
    # Find overly complex prompts
    for name, prompt_data in all_prompts.items():
        content = prompt_data["content"]
        complexity_indicators = [
            len(content) > 2000,  # Very long
            content.count('\n') > 50,  # Many lines
            len(re.findall(r'\{[^}]+\}', content)) > 10,  # Many placeholders
        ]
        
        if sum(complexity_indicators) >= 2:
            optimization_report["overly_complex_prompts"].append({
                "prompt": name,
                "length": len(content),
                "lines": content.count('\n') + 1,
                "placeholders": len(re.findall(r'\{[^}]+\}', content))
            })
    
    # Generate optimization suggestions
    if optimization_report["duplicate_content"]:
        optimization_report["optimization_suggestions"].append(
            f"Found {len(optimization_report['duplicate_content'])} sets of duplicate prompts - consider consolidating"
        )
    
    if len(optimization_report["unused_prompts"]) > 5:
        optimization_report["optimization_suggestions"].append(
            f"Found {len(optimization_report['unused_prompts'])} unused prompts - consider removing or archiving"
        )
    
    if optimization_report["overly_complex_prompts"]:
        optimization_report["optimization_suggestions"].append(
            f"Found {len(optimization_report['overly_complex_prompts'])} complex prompts - consider breaking into smaller parts"
        )
    
    return optimization_report
