# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import dataclasses as dc
from datetime import datetime
import struct
from typing import Any, Literal
from .crc16pure import crc16xmodem
from .model import BsbCommand, BsbModel, I18nstr
from .errors import DecodeError
from .payload_decode import decode
from .payload_encode import encode

__all__ = ["BsbTelegram"]

_PACKETTYPES = {
    2: "inf",
    3: "set",
    4: "ack",
    6: "get",
    7: "ret",
}

_PACKETTYPES_R = {value: key for key, value in _PACKETTYPES.items()}


@dc.dataclass
class BsbTelegram(object):
    """Representation of a BSB telegram.
    Use BsbTelegram.deserialize() to parse raw data into telegrams.
    Use BsbTelegram.serialize() to convert telegram into raw data.
    """

    command: BsbCommand
    src: int = 0
    """Source address (0...255)"""
    dst: int = 0
    """Destination address (0...255)"""
    packettype: Literal["inf", "set", "ack", "get", "ret"] = "get"
    """Telegram type
    
    inf: unsolicited information from device
    set: setting value to device
    ack: acknowledgement from device (response to set)
    get: request value from device
    ret: returned value from device (response to get)
    """
    rawdata: bytes = b""
    """Raw payload data (bytes), if telegram was received from bus."""
    data: Any = None
    """Payload data (decoded or to set)"""
    timestamp: float = 0
    """Timestamp when telegram was received/sent (epoch time)"""

    @property
    def field(o):
        return o.command

    @classmethod
    def deserialize(cls, data: bytes, device: BsbModel) -> list["BsbTelegram | tuple[bytes, str]"]:
        """returns a list of BsbTelegrams and unparseable data, if any.
        For unparseable data, the list entry is a tuple: (data sequence, error message)
        Order follows the input stream order.
        """
        indata = data
        assert isinstance(indata, bytes)
        result = []

        while indata:
            try:
                t, indata = cls._parse(indata, device)
                result.append(t)
            except DecodeError as e:
                junk, indata = cls._skip(indata)
                result.append((junk, e.args[0]))
        return result

    @classmethod
    def _skip(cls, data):
        """skip to next possible start byte (recognised by magic 0xDC byte).
        returns data splitted in (junk, gold) where junk are the skipped bytes
        and gold is the rest.
        """
        try:
            idx = data.index(b"\xdc", 1)
        except ValueError:
            return data, b""
        return data[:idx], data[idx:]

    @classmethod
    def _validate(cls, data: bytes):
        """Checks start marker, data length, packet type, crc checksum.

        Raises DecodeError on failure.
        """
        if data[0] != 0xDC:
            raise DecodeError("bad start marker")
        if len(data) < 4 or len(data) < data[3]:
            raise DecodeError("incomplete telegram")

        if data[4] not in _PACKETTYPES:
            raise DecodeError("unknown packet type: %d" % data[4])

        tlen = data[3]
        if tlen < 11:
            raise DecodeError("bad length: telegram cannot be shorter than 11 bytes")
        crc = crc16xmodem(data[:tlen])
        if crc != 0:
            pretty = "".join("%0.2X " % i for i in data[:tlen])
            raise DecodeError("bad crc checksum for: " + pretty)

    @classmethod
    def _parse(cls, data: bytes, device: BsbModel):
        """return cls instance, rest of data"""
        cls._validate(data)

        src = data[1] ^ 0x80
        dst = data[2]
        dlen = data[3]
        packettype: Literal["inf", "set", "ack", "get", "ret"] = _PACKETTYPES[data[4]]  # type: ignore

        fidbytes = [data[i] for i in (5, 6, 7, 8)]
        # For requests, byte 5+6 are swapped.
        if packettype in ["get", "set"]:
            fidbytes[0], fidbytes[1] = fidbytes[1], fidbytes[0]

        fieldid = 0
        mult = 0x1000000
        for d in fidbytes:
            fieldid, mult = d * mult + fieldid, mult // 0x100

        field = BsbCommand.unknown(fieldid)
        if device:
            # Try to identify the field. if not found, keep the "null" field.
            field = device.commands_by_telegram_id.get(fieldid, field)
        # Expects list of ints
        rawdata = data[9 : dlen - 2]
        if rawdata and field.type:
            value = decode(rawdata, field.type, packettype=packettype)
        else:
            value = None

        if packettype not in ["ret", "set", "inf"]:
            assert value is None
            assert rawdata == b""

        t = cls(
            command=field,
            src=src,
            dst=dst,
            packettype=packettype,
            rawdata=rawdata,
            data=value,
        )
        return t, data[dlen:]

    def serialize(o, validate=True):
        """returns ready-to-send telegram as binary string."""
        result = [
            0xDC,
            o.src ^ 0x80,
            o.dst,
            0,  # length to be set
            _PACKETTYPES_R[o.packettype],
        ]
        id = o.command.telegram_id
        id = [(id & 0xFF000000) >> 24, (id & 0xFF0000) >> 16, (id & 0xFF00) >> 8, id & 0xFF]
        if o.packettype in ["get", "set"]:
            id[1], id[0] = id[0], id[1]
        result += id

        if o.packettype == "ret" or o.packettype == "set":
            assert o.command.type is not None, "Cannot serialize telegram without type information"
            result += list(
                encode(
                    o.data, o.command.type, o.command, validate=validate, packettype=o.packettype
                )
            )

        # set length
        result[3] = len(result) + 2

        # add crc
        crc = crc16xmodem(result)
        result.append((crc & 0xFF00) >> 8)
        result.append(crc & 0xFF)
        return bytes(result)

    # let's try dataclass builtin representation for now
    def __str__(o):
        rawdata = "".join(["%0.2X " % i for i in o.rawdata])
        ts = " @" + datetime.fromtimestamp(o.timestamp).strftime("%H:%M:%S.%f") if o.timestamp else ""
        unit = o.field.unit
        unit = " " + unit if unit else ""
        if o.field.disp_id > 0:
            fieldname = f"{o.field.disp_id} {o.field.disp_name}"
        else:
            fieldname = f"{o.field.disp_name} 0x{o.field.telegram_id:08X}"

        if o.packettype in ("ret", "set", "inf"):
            data_txt = f" = {o.data}{unit} [raw:{rawdata}]"
        else:
            data_txt = ""

        return f"<BsbTelegram {o.src} -> {o.dst}: {o.packettype} {fieldname}{data_txt}{ts}>"


def runtest():
    fh = open("dump.txt", "r")
    s = fh.read()
    fh.close()

    data = s.replace("\n", "").replace(" ", "").decode("hex")
    result = BsbTelegram.deserialize(data, None)

    for r in result:
        print(repr(r))


if __name__ == "__main__":
    runtest()
