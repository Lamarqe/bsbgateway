# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

from typing import Literal
from .model import BsbCommand, BsbType, BsbDatatype, BsbCommandFlags, ScheduleEntry
from .errors import EncodeError, ValidateError
import struct
import datetime as dt


def encode(data:object, bsb_type:BsbType, command:BsbCommand, validate:bool=True, packettype:Literal["ret", "set"]="set") -> bytes:
    """Encodes data according to type.
    
    The flag byte meaning depends on packettype:
    - For 'ret' packets: 0 = value, 1 = null
    - For 'set' packets: 1 = non-nullable field, 5 = null (nullable field), 6 = value (nullable field)
    
    If validate=True, checks soft constraints as follows. 

    * check that numeric values are within min/max range, if given.
    * check that value is one of the enum values, if set.
    * check that command has the read/write flag set
    * check that time fields are within valid ranges

    If validate=False, you can send anything that can be converted to bytes, **at your own peril**.

    Raises EncodeError on failure.
    """
    if validate:
        # Check if command is writable
        if BsbCommandFlags.Readonly in command.flags:
            raise ValidateError("Command is read-only")
        
        # Check enum values
        if command.enum and data is not None:
            if data not in command.enum:
                raise ValidateError(f"Value {data} not in enum values: {list(command.enum.keys())}")
        
        # Check min/max range for numeric values
        if isinstance(data, (int, float)) and data is not None:
            if command.min_value is not None and data < command.min_value:
                raise ValidateError(f"Value {data} is below minimum {command.min_value}")
            if command.max_value is not None and data > command.max_value:
                raise ValidateError(f"Value {data} is above maximum {command.max_value}")

    if bsb_type.datatype == BsbDatatype.Raw:
        return bytes(data) #type:ignore
    
    # Determine the appropriate flag byte based on packet type and data
    if data is None:
        if not bsb_type.nullable:
            raise EncodeError("Type is not nullable, cannot encode None")
        # For null values
        if packettype == "ret":
            flag = 0x01  # ret: null value
        else:  # set packet
            flag = 0x05  # set: null value for nullable field
    else:
        # For non-null values
        if packettype == "ret":
            flag = 0x00  # ret: normal value
        else:  # set packet
            if bsb_type.nullable:
                flag = 0x06  # set: value for nullable field
            else:
                flag = 0x01  # set: value for non-nullable field
    
    # Get the appropriate encoder (only for non-null values)
    if data is not None:
        if bsb_type.name in _CUSTOM_ENCODERS:
            encoder = _CUSTOM_ENCODERS[bsb_type.name]
        else:
            if bsb_type.datatype not in _ENCODERS:
                raise EncodeError(f"No encoder for datatype {bsb_type.datatype}")
            encoder = _ENCODERS[bsb_type.datatype]
        
        payload = encoder(data, bsb_type)
    else:
        # For null values, payload is all zeros
        payload = b'\x00' * bsb_type.payload_length
    
    # Add flag byte for flagged types (not for TimeProgram and String)
    if bsb_type.datatype not in (BsbDatatype.TimeProgram, BsbDatatype.String, BsbDatatype.Raw):
        return bytes([flag]) + payload
    else:
        # TimeProgram and String don't have flag bytes
        return payload

def encode_unsure(data: object, bsb_type:BsbType) -> bytes:
    """I'm not sure how to correctly encode this field.
    
    Will always raise an EncodeError.
    """
    raise EncodeError(f"Not sure about type {bsb_type.name} - won't encode for safety reasons.")

def encode_vals(data:object, bsb_type:BsbType) -> bytes:
    """Encodes numeric value (int or float).
    
    Converts float to int using the type's factor.
    """
    if not isinstance(data, (int, float)):
        raise EncodeError(f"Expected numeric value, got {type(data).__name__}")
    
    if bsb_type.factor != 1:
        # Convert float to int using factor
        intval = int(round(data * bsb_type.factor))
    else:
        intval = int(data)
    
    assert bsb_type.payload_length in [1, 2, 4]
    code = {1: "b", 2: "h", 4: "i"}[bsb_type.payload_length]
    if bsb_type.unsigned or bsb_type.datatype != BsbDatatype.Vals:
        code = code.upper()
    
    return struct.pack(">" + code, intval)


def encode_hourminute(data:object, bsb_type:BsbType) -> bytes:
    """Encodes hour/minute time value."""
    if not isinstance(data, dt.time):
        raise EncodeError(f"Expected datetime.time, got {type(data).__name__}")
    
    assert bsb_type.payload_length == 2
    return struct.pack("2b", data.hour, data.minute)


def encode_dt(data:object, bsb_type:BsbType) -> bytes:
    """Encodes datetime types (Datetime, DayMonth, Time, YEAR, VACATIONPROG)."""
    assert bsb_type.payload_length == 8
    
    if bsb_type.name == "YEAR":
        if not isinstance(data, int):
            raise EncodeError(f"YEAR expects int, got {type(data).__name__}")
        year = data
        month, day, dow, hour, minute, second = 0, 0, 0, 0, 0, 0
        flag = 0x0f
    elif bsb_type.name == "VACATIONPROG":
        if not isinstance(data, dt.date):
            raise EncodeError(f"VACATIONPROG expects datetime.date, got {type(data).__name__}")
        year = 1900
        month, day = data.month, data.day
        dow, hour, minute, second = 0, 0, 0, 0
        flag = 0x17
    elif bsb_type.datatype == BsbDatatype.Datetime:
        if not isinstance(data, dt.datetime):
            raise EncodeError(f"Datetime expects datetime.datetime, got {type(data).__name__}")
        year = data.year
        month, day = data.month, data.day
        hour, minute, second = data.hour, data.minute, data.second
        dow = 0
        flag = 0x00
    elif bsb_type.datatype == BsbDatatype.DayMonth:
        if not isinstance(data, dt.date):
            raise EncodeError(f"DayMonth expects datetime.date, got {type(data).__name__}")
        year = 1900
        month, day = data.month, data.day
        dow, hour, minute, second = 0, 0, 0, 0
        flag = 0x16
    elif bsb_type.datatype == BsbDatatype.Time:
        if not isinstance(data, dt.time):
            raise EncodeError(f"Time expects datetime.time, got {type(data).__name__}")
        year = 1900
        month, day = 1, 1
        hour, minute, second = data.hour, data.minute, data.second
        dow = 0
        flag = 0x1d
    else:
        raise EncodeError(f"Could not encode datetime field of type {bsb_type.datatype}")
    
    year_offset = year - 1900
    return struct.pack("8b", year_offset, month, day, dow, hour, minute, second, flag)


def encode_string(data:object, bsb_type:BsbType) -> bytes:
    """Encodes string value.
    
    Note: String types follow the BSB protocol's 22-byte maximum limit.
    The decode function uses min(payload_length+1, 22), so we encode to that size.
    """
    if not isinstance(data, str):
        raise EncodeError(f"Expected str, got {type(data).__name__}")
    
    encoded = data.encode("latin-1")
    # Calculate the expected length following decode's expect_len logic
    expected_len = min(bsb_type.payload_length + 1, 22)
    
    if len(encoded) > bsb_type.payload_length:
        raise EncodeError(f"String too long: {len(encoded)} > {bsb_type.payload_length}")
    
    return encoded + b'\x00' * (expected_len - len(encoded))


def encode_enum(data:object, bsb_type:BsbType) -> bytes:
    """Encodes enum value (single byte)."""
    if not isinstance(data, int):
        raise EncodeError(f"Expected int for enum, got {type(data).__name__}")
    
    if data < 0 or data > 255:
        raise EncodeError(f"Enum value {data} out of range [0, 255]")
    
    assert bsb_type.payload_length == 1
    return struct.pack("B", data)


def encode_timeprogram(data:object, bsb_type:BsbType) -> bytes:
    """Encodes time program (on/off schedule).
    
    Expects a list of up to three ScheduleEntry objects.
    Note: TimeProgram types have payload_length = 11 but actually encode 12 bytes,
    accounting for the +1 that decode adds.
    """
    if not isinstance(data, list):
        raise EncodeError(f"Expected list of ScheduleEntry, got {type(data).__name__}")
    
    if len(data) > 3:
        raise EncodeError(f"TimeProgram can have at most 3 entries, got {len(data)}")
    
    # TimeProgram always produces payload_length+1 bytes (12 bytes for payload_length=11)
    expected_bytes = bsb_type.payload_length + 1
    assert expected_bytes == 12, f"Expected TimeProgram to encode to 12 bytes, got {expected_bytes}"
    
    result = bytearray(12)
    
    for idx, entry in enumerate(data):
        if not isinstance(entry, ScheduleEntry):
            raise EncodeError(f"Expected ScheduleEntry, got {type(entry).__name__}")
        
        ofs = idx * 4
        h1, m1 = entry.on.hour, entry.on.minute
        h2, m2 = entry.off.hour, entry.off.minute
        
        # Validate time ranges
        if not (0 <= h1 <= 23 and 0 <= m1 <= 59):
            raise EncodeError(f"Invalid on-time: {h1}:{m1}")
        if not (0 <= h2 <= 23 and 0 <= m2 <= 59):
            raise EncodeError(f"Invalid off-time: {h2}:{m2}")
        
        result[ofs:ofs+4] = struct.pack("4B", h1, m1, h2, m2)
    
    # Mark unused entries as disabled (set bit 7 of first byte)
    for idx in range(len(data), 3):
        ofs = idx * 4
        result[ofs] = 0x80
    
    return bytes(result)


_ENCODERS = {
    BsbDatatype.Vals: encode_vals,
    BsbDatatype.Bits: encode_unsure,
    BsbDatatype.Enum: encode_enum,
    BsbDatatype.Datetime: encode_dt,
    BsbDatatype.DayMonth: encode_dt,
    BsbDatatype.HourMinutes: encode_hourminute,
    BsbDatatype.Time: encode_dt,
    BsbDatatype.TimeProgram: encode_timeprogram,
    BsbDatatype.String: encode_string,
    BsbDatatype.Date: encode_unsure,
}

# Exceptions :-)
_CUSTOM_ENCODERS = {
    "YEAR": encode_dt,
    "VACATIONPROG": encode_dt,
}

