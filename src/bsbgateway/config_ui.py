# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

"""Interactive terminal-based configuration UI.

This module provides an interactive menu for configuring the BsbGateway
configuration objects. It uses dataclass introspection to automatically
build menus from nested configuration structures.
"""

from copy import deepcopy
import logging
import json
import inspect
import ast
from typing import Any, Type, TypeVar
import dataclasses as dc

L = lambda: logging.getLogger(__name__)

T = TypeVar('T')

def _get_field_display_name(field_name: str) -> str:
    """Convert field_name to readable display name."""
    return field_name.replace('_', ' ').title()


def _extract_field_docstring(dataclass_type: Type, field_name: str) -> str:
    """Extract docstring for a specific field from a dataclass.
    
    Uses AST parsing to extract field docstrings from the class definition.
    Falls back to empty string if not found.
    
    Args:
        dataclass_type: The dataclass type
        field_name: Name of the field
        
    Returns:
        Field docstring or empty string
    """
    try:
        source = inspect.getsource(dataclass_type)
        tree = ast.parse(source)
        
        # Find the class definition
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == dataclass_type.__name__:
                # Look for field annotations with following docstring
                for i, item in enumerate(node.body):
                    # Match AnnAssign (annotated assignment like "field: type = default")
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        if item.target.id == field_name:
                            # Check if there's a string constant after this assignment
                            if i + 1 < len(node.body):
                                next_item = node.body[i + 1]
                                if isinstance(next_item, ast.Expr) and isinstance(next_item.value, ast.Constant):
                                    if isinstance(next_item.value.value, str):
                                        return next_item.value.value.strip()
                            break
                break
    except (OSError, TypeError, SyntaxError):
        L().debug(f"Could not extract docstring for {field_name} in {dataclass_type.__name__}", exc_info=True)
    
    return ""


def _get_field_input_prompt(dataclass_type: Type, field: dc.Field, current_value: Any,default_value:Any) -> str:
    """Create input prompt for a field with its docstring and default value.
    
    Args:
        dataclass_type: The dataclass type (for extracting docstrings)
        field: The dataclass field
        current_value: Current value of the field
        default_value: Default value of the field
        
    Returns:
        Formatted input prompt string
    """
    type_str = field.type.__name__ if hasattr(field.type, '__name__') else str(field.type)
    display_name = _get_field_display_name(field.name)
    
    docstring = _extract_field_docstring(dataclass_type, field.name)
    doc_str = f"\n  {docstring}" if docstring else ""
    
    # Show default value if it exists and differs from current
    default_str = ""
    if default_value is not dc.MISSING:
        default_str = f" [default: {default_value}]"
    
    return f"{display_name} ({type_str}){doc_str}\n\n{field.name}{default_str}"


def _convert_input(value_str: str, field_type: Type) -> Any:
    """Convert string input to appropriate type.
    
    Args:
        value_str: User input string
        field_type: Target type for conversion
        
    Returns:
        Converted value
        
    Raises:
        ValueError, TypeError: If conversion fails
    """
    
    # Handle basic types
    if field_type == str:
        return value_str
    elif field_type == int:
        return int(value_str)
    elif field_type == float:
        return float(value_str)
    elif field_type == bool:
        L().info("Converting to bool: %s", value_str)
        return value_str.lower() in ('true', '1', 'yes', 'on', 'y')
    else:
        # Try JSON parsing for complex types (lists, dicts, etc)
        try:
            return json.loads(value_str)
        except json.JSONDecodeError:
            # Fall back to ast.literal_eval for other literals
            try:
                return ast.literal_eval(value_str)
            except (ValueError, SyntaxError):
                return value_str


def _configure_dataclass_menu(obj: T, parent_name: str = "", is_submenu: bool = False) -> tuple[T, bool]:
    """Interactively configure a dataclass instance with a menu interface.
    
    Args:
        obj: Dataclass instance to configure
        parent_name: Name of the parent for display (used in submenus)
        is_submenu: Whether this is a submenu (affects exit options)
        
    Returns:
        Tuple of (modified_obj, changed) where changed is True if user wants to save
    """
    if not dc.is_dataclass(obj):
        L().warning(f"{obj.__class__.__name__} is not a dataclass")
        return obj, False
    
    dataclass_type = type(obj)
    fields = [f for f in dc.fields(obj) if not f.name.startswith('_')]
    new_obj = deepcopy(obj)
    
    # Pre-compute default values for all fields
    defaults = {}
    for field in fields:
        default_value = field.default
        if default_value is dc.MISSING and field.default_factory is not dc.MISSING:
            default_value = field.default_factory()
        defaults[field.name] = default_value

    is_changed = False

    while True:
        # Build menu items
        menu_title = f"{_get_field_display_name(parent_name)}" if parent_name else "BsbGateway Configuration"
        print(f"\n=== {menu_title} ===\n")
        print(inspect.cleandoc(str(obj.__doc__)))
        print()
        
        items = []
        field_indices = {}
        
        for i, field in enumerate(fields, 1):
            current_value = getattr(new_obj, field.name)
            display_name = _get_field_display_name(field.name)
            field_indices[i] = field
            
            # Show summary for dataclasses
            if dc.is_dataclass(current_value) and not isinstance(current_value, (str, bytes)):
                items.append(f"  {i}) {display_name} ...")
            else:
                items.append(f"  {i}) {display_name}: {current_value}")

        # Special options
        # Bsb2TcpSettings
        if hasattr(obj, "get_random_token"):
            items.append("")
            items.append("  t) Generate random token")
        
        # Exit options
        items.append("")
        if is_submenu:
            items.append(f"  a) or Return: Accept + back to previous menu")
            items.append(f"  x) Discard + back to previous menu")
        else:
            items.append(f"  a) or Return: Accept + save changes")
            items.append(f"  x) Exit without saving")

        
        for item in items:
            print(item)
        
        try:
            choice = input("\nSelect option: ").strip()
        except KeyboardInterrupt:
            return obj, False
        
        if choice == "a" or choice == "":
            return new_obj, is_changed
        elif choice == "x":
            return obj, False
        elif choice == "t":
            new_obj.token = new_obj.get_random_token() #type: ignore

        try:
            choice_num = int(choice)
        except ValueError:
            choice_num = -1  # Invalid number
        if choice_num in field_indices:
            field = field_indices[choice_num]
            current_value = getattr(new_obj, field.name)
            
            if dc.is_dataclass(current_value) and not isinstance(current_value, (str, bytes)):
                # Recurse into submenu
                new_value, field_changed = _configure_dataclass_menu(current_value, field.name, is_submenu=True)
                if field_changed:
                    is_changed = True
                    setattr(new_obj, field.name, new_value)
            else:
                # Single field edit
                prompt = _get_field_input_prompt(dataclass_type, field, current_value, defaults.get(field.name, dc.MISSING))
                user_input = input(f"{prompt} = ").strip()
                
                if user_input != "":
                    # Empty input: do not change
                    try:
                        new_value = _convert_input(user_input, field.type)
                    except (ValueError, TypeError) as e:
                        print(f"Invalid input: {e}")
                    else:
                        is_changed = is_changed or (new_value != current_value)
                        setattr(new_obj, field.name, new_value)
                        L().debug(f"Set {field.name} to {new_value}")
        else:
            print("Invalid selection")


def run(config: T) -> tuple[T, bool]:
    """Main entry point for interactive configuration.
    
    Args:
        config: Configuration object to edit
    """
    L().info("Starting interactive configuration")
    try:
        return _configure_dataclass_menu(config, is_submenu=False)
    except Exception as e:
        L().error(f"Configuration error: {e}", exc_info=True)
        print(f"Error: {e}")
        return config, False
