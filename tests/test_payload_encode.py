import pytest
from attr import evolve
import datetime as dt
from bsbgateway.bsb.model import (
    BsbType, BsbDatatype, I18nstr, ScheduleEntry, 
    BsbCommand, BsbDevice
)
from bsbgateway.bsb.payload_encode import encode, EncodeError
from bsbgateway.bsb.errors import ValidateError
from bsbgateway.bsb.payload_decode import decode

KW = {"unit": I18nstr(), "name": "test"}

int8 = BsbType(datatype=BsbDatatype.Vals, payload_length=1, enable_byte=1, **KW)
uint8 = evolve(int8, unsigned=True)
int16 = evolve(int8, payload_length=2)
uint16 = evolve(int16, unsigned=True)
int32 = evolve(int8, payload_length=4)
int16_10 = evolve(int16, factor=10)

bits = BsbType(datatype=BsbDatatype.Bits, payload_length=1, enable_byte=1, **KW)
enum = evolve(bits, datatype=BsbDatatype.Enum)

year = BsbType(unit=I18nstr(), name="YEAR", datatype=BsbDatatype.Vals, payload_length=8, enable_byte=1)
dttm = BsbType(datatype=BsbDatatype.Datetime, payload_length=8, enable_byte=1, **KW)
ddmm = evolve(dttm, datatype=BsbDatatype.DayMonth)
ddmm_v = evolve(ddmm, name="VACATIONPROG")
thms = evolve(dttm, datatype=BsbDatatype.Time)

hhmm = evolve(int16, datatype=BsbDatatype.HourMinutes)

str5 = BsbType(datatype=BsbDatatype.String, payload_length=5, enable_byte=1, **KW)
str22 = evolve(str5, payload_length=22)

# TimeProgram has 12 bytes of schedule data, but payload_length=11 (the +1 is added by decode)
tmpr = BsbType(datatype=BsbDatatype.TimeProgram, payload_length=11, enable_byte=8, **KW)

# Nullable type
int8_nullable = evolve(int8, enable_byte=6)

def SE(h1, m1, h2, m2):
    return ScheduleEntry(
        on=dt.time(h1, m1),
        off=dt.time(h2, m2),
    )

# Create a dummy command for encoding tests
def make_command(**kwargs):
    defaults = {
        "parameter": 1,
        "command": "0x12345678",
        "description": I18nstr({"EN": "test"}),
        "device": [BsbDevice(family=255, var=255)],
        "flags": [],
        "enum": {},
    }
    defaults.update(kwargs)
    return BsbCommand(**defaults)


@pytest.mark.parametrize(
    "value, bsb_type",
    [
        (10, int8),
        (-1, int8),
        (255, uint8),
        (258, int16),
        (-1, int16),
        (65535, uint16),
        (26.0, int16_10),
        (65536, int32),
        (254, enum),
        (1985, year),
        (dt.datetime(1985, 10, 26, 1, 21, 1), dttm),
        (dt.date(1900, 10, 26), ddmm),
        (dt.date(1900, 10, 26), ddmm_v),
        (dt.time(1, 21, 1), thms),
        (dt.time(1, 21, 0), hhmm),
        ("efg", str5),
        ("efg", str22),  # str22 will be capped at 21 bytes for encoding due to BSB protocol limit
        ([], tmpr),
        ([SE(1, 2, 3, 4)], tmpr),
        ([SE(1, 2, 3, 4), SE(2, 3, 4, 5)], tmpr),
        ([SE(1, 2, 3, 4), SE(1, 0, 3, 0), SE(2, 3, 4, 5)], tmpr),
        (None, int8_nullable),
    ]
)
def test_encode_decode_roundtrip(value, bsb_type):
    """Test that encode and decode are proper inverses.
    
    For roundtrip testing, we test first with ret, then with set packet.
    """
    cmd = make_command()
    
    # Encode as ret packet
    encoded = encode(value, bsb_type, cmd, validate=False, packettype="ret")
    
    # Check flag byte for ret packets: 0 for value, 1 for null
    if bsb_type.datatype not in (BsbDatatype.TimeProgram, BsbDatatype.String, BsbDatatype.Raw):
        expected_flag = 1 if value is None else 0
        assert encoded[0] == expected_flag, f"Wrong flag for {value}, got {encoded[0]}, expected {expected_flag}"
    
    # Decode and verify
    decoded = decode(encoded, bsb_type, packettype="ret")
    assert decoded == value, f"Decoded {decoded} != {value}"
    assert type(decoded) is type(value)

    encoded = encode(value, bsb_type, cmd, validate=False, packettype="set")
    decoded = decode(encoded, bsb_type, packettype="set")
    assert decoded == value, f"Decoded {decoded} != {value} (set packet)"

@pytest.mark.parametrize(
    "value, bsb_type",
    [
        (b'abc', bits),
    ]
)
def test_encode_unsure(value, bsb_type):
    cmd = make_command()
    with pytest.raises(EncodeError):
        _ = encode(value, bsb_type, cmd, packettype="set")


def test_encode_validation():
    """Test that encode validates according to command flags."""
    from bsbgateway.bsb.model import BsbCommandFlags
    
    cmd_readonly = make_command(flags=[BsbCommandFlags.Readonly])
    cmd_normal = make_command()
    
    # Readonly command should fail with validation
    with pytest.raises(ValidateError, match="read-only"):
        encode(10, int8, cmd_readonly, validate=True)
    
    # Without validation it should work (flag 1 for non-nullable set packet)
    encoded = encode(10, int8, cmd_readonly, validate=False, packettype="set")
    assert encoded == b'\x01\x0a'
    
    # For ret packet, flag should be 0
    encoded = encode(10, int8, cmd_readonly, validate=False, packettype="ret")
    assert encoded == b'\x00\x0a'


def test_encode_enum_validation():
    """Test enum value validation."""
    enum_type = evolve(enum)
    cmd = make_command(enum={254: I18nstr({"EN": "value254"})})
    
    # Valid enum value for set packet (flag 1)
    encoded = encode(254, enum_type, cmd, validate=True, packettype="set")
    assert encoded == b'\x01\xfe'
    
    # Valid enum value for ret packet (flag 0)
    encoded = encode(254, enum_type, cmd, validate=True, packettype="ret")
    assert encoded == b'\x00\xfe'
    
    # Invalid enum value
    with pytest.raises(ValidateError, match="not in enum"):
        encode(100, enum_type, cmd, validate=True)


def test_encode_min_max_validation():
    """Test min/max range validation."""
    cmd = make_command(min_value=0.0, max_value=100.0)
    
    # Value below minimum
    with pytest.raises(ValidateError, match="below minimum"):
        encode(-1.0, int16_10, cmd, validate=True)
    
    # Value above maximum
    with pytest.raises(ValidateError, match="above maximum"):
        encode(101.0, int16_10, cmd, validate=True)
    
    # Value in range
    encoded = encode(50.0, int16_10, cmd, validate=True)
    assert encoded is not None


def test_encode_nullable():
    """Test encoding of null values for nullable types.
    
    For set packets:
    - Nullable field with value: flag 6
    - Nullable field with None: flag 5
    
    For ret packets:
    - Any field with value: flag 0
    - Any field with None: flag 1
    """
    cmd = make_command()
    
    # Nullable type with None value - set packet uses flag 5
    encoded = encode(None, int8_nullable, cmd, validate=False, packettype="set")
    assert encoded == b'\x05\x00'
    
    # Nullable type with None value - ret packet uses flag 1
    encoded = encode(None, int8_nullable, cmd, validate=False, packettype="ret")
    assert encoded == b'\x01\x00'
    decoded = decode(encoded, int8_nullable, packettype="ret")
    assert decoded is None
    
    # Nullable type with actual value - set packet uses flag 6
    encoded = encode(10, int8_nullable, cmd, validate=False, packettype="set")
    assert encoded == b'\x06\x0a'
    
    # Nullable type with actual value - ret packet uses flag 0
    encoded = encode(10, int8_nullable, cmd, validate=False, packettype="ret")
    assert encoded == b'\x00\x0a'
    decoded = decode(encoded, int8_nullable, packettype="ret")
    assert decoded == 10
    
    # Non-nullable type with None value should fail
    with pytest.raises(EncodeError, match="not nullable"):
        encode(None, int8, cmd, validate=False)


def test_encode_invalid_types():
    """Test that encode rejects invalid input types."""
    cmd = make_command()
    
    # String value for numeric type
    with pytest.raises(EncodeError, match="Expected numeric"):
        encode("not a number", int8, cmd, validate=False)
    
    # Int value for datetime type
    with pytest.raises(EncodeError, match="expects"):
        encode(123, dttm, cmd, validate=False)
    
    # Wrong datetime type
    with pytest.raises(EncodeError, match="expects"):
        encode(dt.date(2000, 1, 1), dttm, cmd, validate=False)


def test_encode_time_validation():
    """Test time field validation."""
    cmd = make_command()
    
    # Valid schedule entry encodes and decodes correctly
    encoded = encode([SE(10, 30, 12, 0)], tmpr, cmd, validate=False)
    # Schedule data has no flag byte. Can be checked directly.
    decoded = decode(encoded, tmpr)
    assert decoded == [SE(10, 30, 12, 0)]


def test_encode_string_length():
    """Test that strings are properly padded and truncated."""
    cmd = make_command()
    
    # String too long
    with pytest.raises(EncodeError, match="too long"):
        encode("abcdefgh", str5, cmd, validate=False)
    
    # String with proper length gets padded
    # str5 has payload_length=5, so expected_len = min(6, 22) = 6
    encoded = encode("abc", str5, cmd, validate=False)
    assert encoded == b'abc\x00\x00\x00'  # 3 chars + 3 padding = 6 total
    assert len(encoded) == 6
    
    # Decode should strip null terminator
    decoded = decode(encoded, str5)
    assert decoded == "abc"


def test_encode_timeprogram_max_entries():
    """Test that timeprogram rejects more than 3 entries."""
    cmd = make_command()
    
    entries = [SE(i, 0, i+1, 0) for i in range(4)]
    with pytest.raises(EncodeError, match="at most 3"):
        encode(entries, tmpr, cmd, validate=False)


def test_encode_timeprogram_disabled_entries():
    """Test that disabled timeprogram entries are properly marked."""
    cmd = make_command()
    
    # Only one entry - other two should be disabled (0x80 flag)
    # No flag byte for TimeProgram type
    encoded = encode([SE(1, 2, 3, 4)], tmpr, cmd, validate=False)
    
    # First 4 bytes: 01 02 03 04
    # Next 4 bytes: 80 00 00 00 (disabled)
    # Last 4 bytes: 80 00 00 00 (disabled)
    assert encoded == bytes([1, 2, 3, 4, 0x80, 0, 0, 0, 0x80, 0, 0, 0])
    
    # Decode should return only the enabled entries
    decoded = decode(encoded, tmpr)
    assert decoded == [SE(1, 2, 3, 4)]


# ============ Raw type tests ============

def test_encode_raw_simple_bytes():
    """Test that Raw type passes through bytes unchanged."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    # Simple byte sequence
    test_bytes = b'\x01\x02\x03\x04'
    encoded = encode(test_bytes, raw_type, cmd, validate=False)
    
    # Raw type should return bytes as-is, without flag byte
    assert encoded == test_bytes
    assert isinstance(encoded, bytes)


def test_encode_raw_empty_bytes():
    """Test that Raw type handles empty bytes."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    encoded = encode(b'', raw_type, cmd, validate=False)
    assert encoded == b''


def test_encode_raw_long_bytes():
    """Test that Raw type handles byte sequences longer than 22 bytes."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    # Create a byte sequence longer than the 22-byte protocol limit
    # (Raw type bypasses this limit since it's for unknown commands)
    test_bytes = bytes(range(256))
    encoded = encode(test_bytes, raw_type, cmd, validate=False)
    
    assert encoded == test_bytes
    assert len(encoded) == 256


def test_encode_raw_packettype_ret():
    """Test that Raw type doesn't use flag bytes for ret packets."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    test_bytes = b'\xAA\xBB\xCC\xDD'
    encoded = encode(test_bytes, raw_type, cmd, packettype="ret", validate=False)
    
    # No flag byte should be added
    assert encoded == test_bytes
    assert encoded[0] == 0xAA  # First byte should be unchanged


def test_encode_raw_packettype_set():
    """Test that Raw type doesn't use flag bytes for set packets."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    test_bytes = b'\x11\x22\x33\x44'
    encoded = encode(test_bytes, raw_type, cmd, packettype="set", validate=False)
    
    # No flag byte should be added
    assert encoded == test_bytes
    assert encoded[0] == 0x11  # First byte should be unchanged


def test_encode_decode_raw_roundtrip():
    """Test that encode/decode are inverses for Raw type."""
    cmd = make_command()
    raw_type = BsbType.raw()
    
    # Various test byte sequences
    test_cases = [
        b'\x00',
        b'\xFF',
        b'\x01\x02\x03',
        bytes(range(16)),
        b'\xDE\xAD\xBE\xEF',
    ]
    
    for test_bytes in test_cases:
        # Encode
        encoded = encode(test_bytes, raw_type, cmd, validate=False)
        # Decode
        decoded = decode(encoded, raw_type)
        
        assert decoded == test_bytes, f"Roundtrip failed for {test_bytes.hex()}"

