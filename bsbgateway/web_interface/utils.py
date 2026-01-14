# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>
"""Utility functions for the web interface."""


def format_readonly_value(field, value):
    """Format a read-only field value for display."""
    if field.type_name == 'choice':
        return f"{value[0]} {value[1]}"
    elif field.type_name == 'time':
        return f"{value[0]:02d}:{value[1]:02d}"
    elif field.type_name == '':
        dez = ' '.join(map(str, value))
        hx = ' '.join([f'{num:x}' for num in value])
        return f"dec: {dez} / hex: {hx}"
    elif isinstance(value, (int,float)):
        return f"{value:.3g} {field.unit}"
    else:
        return f"{value} {field.unit}"


def format_range(field):
    """Format the valid range for a field."""
    if field.type_name in ('int16', 'temperature', 'int32'):
        min_val = field.min / field.divisor
        max_val = field.max / field.divisor
    else:
        min_val = field.min
        max_val = field.max
    return f"({min_val:g} ... {max_val:g})"
