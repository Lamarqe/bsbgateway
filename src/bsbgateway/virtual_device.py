##############################################################################
#
#    Part of BsbGateway
#    Copyright (C) Johannes Loehnert, 2013-2022
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import sys
import logging

from bsbgateway.bsb.bsb_field import BsbField
log = lambda: logging.getLogger(__name__)
import datetime
import time

from .bsb.old_bsb_telegram import BsbTelegram
from .bsb import broetje_isr_plus

if sys.version_info[0] == 2:
    ashex = lambda b: b.encode('hex')
else:
    ashex = lambda b: b.hex()

TEST_FIELDS = [
    BsbField(0xB5B00000, 100, u'Testfeld', rw=True),    
    BsbField(0xB5B00001, 101, u'Testfeld', rw=True),    
    BsbField(0xB5B00002, 102, u'Testfeld', rw=True),    
    BsbField(0xB5B00003, 103, u'Testfeld', rw=True),    
    BsbField(0xB5B00004, 104, u'Testfeld', rw=True),    
    BsbField(0xB5B00005, 105, u'Testfeld', rw=True),    
    BsbField(0xB5B00006, 106, u'Testfeld', rw=True),    
    BsbField(0xB5B00007, 107, u'Testfeld', rw=True),    
    BsbField(0xB5B00008, 108, u'Testfeld', rw=True),    
    BsbField(0xB5B00009, 109, u'Testfeld', rw=True),    
    BsbField(0xB5B0000A, 110, u'Testfeld', rw=True),    
]

def invert(data):
    return bytes(x ^ 0xff for x in data)


def virtual_device(device=broetje_isr_plus):
    device.fields_by_telegram_id.update({
        f.telegram_id: f for f in TEST_FIELDS
    })
    # TODO: uninvert bytes
    txdata = b''
    state = {
        # Time fields: flag yymmddwd hhmmssfl
        # Datetime
        100: bytes.fromhex("00 370b0500 01150100"), # 1955-11-05 01:21:01
        # (wd: day of week, fl: subtype flag)
        # Time
        101: bytes.fromhex("00 00000000 0d25211D"),
        # Daymonth
        102: bytes.fromhex("00 00070400 00000016"),
        # Year
        103: bytes.fromhex("00 7e000000 0000000F"),
        # Hour-minutes
        104: bytes.fromhex("00 0d25"),
        # Time program
        105: bytes.fromhex("0d00 0d25 1000 1100 8000 0000"),
        # String
        106: bytes.fromhex("65 66 67" + "00"*19),
        # enum
        107: bytes.fromhex("00 01"),
        # temperature (value is 1°C?)
        108: bytes.fromhex("00 00 40"),
        # nullable short
        109: bytes.fromhex("01 0000"),
        # bits
        110: bytes.fromhex("00 FE 65 66 67" + "00"*17),
    }
    while True:
        rxdata = yield txdata
        try:
            txdata = _handle(device, rxdata, state)
        except Exception:
            log().error("Virtual device encountered internal error", exc_info=True)
            txdata = rxdata

def _handle(device, rxdata, state):
    log().debug('Virtual device receives: [%s]'%(ashex(rxdata)))

    # read back written data (as the real bus adapter does)
    txdata = rxdata

    maybe_inv = invert if (rxdata.startswith(b'\x23')) else lambda x:x

    # construct response
    rxdata = maybe_inv(rxdata)
    t = BsbTelegram.deserialize(rxdata, device)[0]
    log().info("decoded packet: %s", t)
    if isinstance(t, tuple):
        # Bad packet. Do not send a response
        return rxdata

    # remember set value for session
    if t.packettype == 'set':
        # horrible hack
        data = bytearray(t.data)
        if data[0] in (1, 6):
            data[0] = 0 # non-null value
        else:
            data[0] = 1 # null value

        log().debug('cached value of %r'%(data,))
        state[t.field.disp_id] = bytes(data)
    t.src, t.dst = t.dst, t.src
    data = rxdata
    t.packettype = {'set':'ack', 'get':'ret'}[t.packettype]
    # for GET, return current state if set, else default value dep. on field type.
    if t.packettype == 'ret':
        try:
            t.data = state[t.field.disp_id]
        except KeyError:
            t.data = {
                'choice': 1,
                'time': datetime.time(13,37),
            }.get(t.field.type_name, 42)
    retdata = t.serialize(validate=False)
    retdata = maybe_inv(retdata)

    time.sleep(0.1)
    log().debug('Virtual device returns : [%s]'%ashex(retdata))
    txdata += retdata
    return txdata
