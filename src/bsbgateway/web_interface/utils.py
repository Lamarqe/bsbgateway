# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>
"""Utility functions for the web interface."""

import datetime
from werkzeug.exceptions import BadRequest
from bsbgateway.bsb.model import BsbCommand, BsbDatatype


def format_readonly_value(field:BsbCommand, value):
    """Format a read-only field value for display."""
    if field.type is None:
        return str(value)
    datatype = field.type.datatype
    if datatype == BsbDatatype.Enum:
        enum_str = field.enum.get(value, "")
        if enum_str:
            return f"{value} ({enum_str})"
        return str(value)
    elif datatype == BsbDatatype.Bits:
        return str(value)
    elif datatype == BsbDatatype.Vals:
        return f"{value:.3g} {field.unit}"
    elif datatype == BsbDatatype.String:
        return str(value)
    elif datatype == BsbDatatype.Datetime:
        return value.strftime('%Y-%m-%d %H:%M:%S')
    elif datatype == BsbDatatype.DayMonth:
        return value.strftime('%d.%m.')
    elif datatype == BsbDatatype.Time:
        return value.strftime('%H:%M:%S')
    elif datatype == BsbDatatype.HourMinutes:
        return value.strftime('%H:%M')
    elif datatype == BsbDatatype.TimeProgram:
        return ', '.join(f"{se.on.strftime('%H:%M')}-{se.off.strftime('%H:%M')}" for se in value)   
    elif datatype == BsbDatatype.Raw:
        dez = ' '.join(map(str, value))
        hx = ' '.join([f'{num:x}' for num in value])
        return f"dec: {dez} / hex: {hx}"
    else:
        return str(value)


def format_range(field:BsbCommand):
    """Format the valid range for a field."""
    if field.min_value is None and field.max_value is None:
        return ""
    if field.min_value is None:
        return f"(<= {field.max_value:g})"
    if field.max_value is None:
        return f"(>= {field.min_value:g})"
    return f"({field.min_value:g} ... {field.max_value:g})"

def parse_value(field: BsbCommand, form_data: dict[str, str]):
    """Parse a value from form data according to field type."""
    # Get form data
    value_str = form_data.get("value", "").strip()
    hour = form_data.get("hour", "").strip()
    minute = form_data.get("minute", "").strip()

    if field.type is None:
        raise BadRequest("Field has no type, cannot set value.")
    datatype = field.type.datatype

    # Convert to appropriate type
    try:
        if value_str == "" and hour == "" and minute == "":
            return None
        elif datatype == BsbDatatype.HourMinutes:
            if hour and minute:
                return datetime.time(int(hour), int(minute))
            else:
                return None
        elif datatype == BsbDatatype.Vals:
            if field.type.factor != 1:
                return float(value_str)
            else:
                return int(value_str)
        # TODO: Other datatypes
        elif datatype == BsbDatatype.Enum:
            return int(value_str)
        else:
            raise BadRequest(f"Setting values of datatype {datatype} not supported.")
    except (ValueError, TypeError) as e:
        raise BadRequest(f"Invalid value: {e}")
