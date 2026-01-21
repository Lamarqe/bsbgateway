# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>
"""Utility functions for the web interface."""

import datetime
from werkzeug.exceptions import BadRequest
from bsbgateway.bsb.model import BsbCommand, BsbDatatype, ScheduleEntry


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

    year = int(form_data.get("year", "0").strip())
    month = int(form_data.get("month", "0").strip())
    day = int(form_data.get("day", "0").strip())
    hour = int(form_data.get("hour", "0").strip())
    minute = int(form_data.get("minute", "0").strip())
    second = int(form_data.get("second", "0").strip())
    set_null = "set_null" in form_data

    if field.type is None:
        raise BadRequest("Field has no type, cannot set value.")
    datatype = field.type.datatype

    # Convert to appropriate type
    try:
        if set_null:
            return None
        elif datatype == BsbDatatype.String:
            return value_str
        elif datatype == BsbDatatype.Vals:
            if field.type.factor != 1:
                return float(value_str)
            else:
                return int(value_str)
        elif datatype == BsbDatatype.Enum:
            return int(value_str)
        elif field.type.name == "YEAR":
            return int(value_str)
        elif datatype == BsbDatatype.Datetime:
            return datetime.datetime(year, month, day, hour, minute, second)
        elif datatype == BsbDatatype.Time:
            return datetime.time(hour, minute, second)
        elif datatype == BsbDatatype.DayMonth:
            return datetime.date(1900, month, day)
        elif datatype == BsbDatatype.HourMinutes:
            return datetime.time(hour, minute)
        elif datatype == BsbDatatype.TimeProgram:
            return _parse_time_program(value_str)
        else:
            # Bits, Raw: not supported for setting
            raise BadRequest(f"Setting values of datatype {datatype} not supported.")
    except (ValueError, TypeError) as e:
        raise BadRequest(f"Invalid value: {e}")

def _parse_time_program(value_str: str) -> list[ScheduleEntry]:
    """Parse time program from string.
    
    String must be in the format "HH:MM-HH:MM, HH:MM-HH:MM, ..."

    Zero to three comma-separated entries are allowed.

    We will automatically sort by start time. However we do not check for overlapping.

    Returns: list of ScheduleEntry objects.
    """
    entries: list[ScheduleEntry] = []
    if not value_str.strip():
        return entries
    parts = [part.strip() for part in value_str.split(",")]
    if len(parts) > 3:
        raise BadRequest("Maximum of three schedule entries allowed.")
    for part in parts:
        try:
            on_str, off_str = part.split("-")
            on_time = datetime.datetime.strptime(on_str.strip(), "%H:%M").time()
            off_time = datetime.datetime.strptime(off_str.strip(), "%H:%M").time()
            entries.append(ScheduleEntry(on=on_time, off=off_time))
        except ValueError:
            raise BadRequest(f"Invalid time program entry: '{part}'")
    # Sort by on time
    entries.sort(key=lambda se: se.on)
    return entries