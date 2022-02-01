##############################################################################
#
#    Part of BsbGateway
#    Copyright (C) Johannes Loehnert, 2013-2015
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
log = lambda: logging.getLogger(__name__)
import datetime
import time
if sys.version_info[0] == 2:
    from Queue import Queue
    ashex = lambda b: b.encode('hex')
else:
    from queue import Queue
    ashex = lambda b: b.hex()

from .event_sources import EventSource

class FakeSerialSource(EventSource):
    
    def __init__(o, name, device=None, *whatever, **more_stuff):
        o.name = name
        o.device = device
        o.stoppable = True
        o.rdqueue = Queue()
        o.state = {}

    def run(o, putevent_func):
        log().warning('WARNING: USING FAKE!! SERIAL PORT')
        while not o._stopflag:
            data = o.rdqueue.get(1)
            if not data: continue
            time.sleep(0.1)
            log().debug('RETURN: [%s]'%ashex(data))
            assert isinstance(data, bytes)
            putevent_func(o.name, (time.time(), data))

    def write(o, data):
        if not isinstance(data, bytes):
            raise ValueError("FakeSerialSource slaps you around a bit with a large trout (because your data was not bytes)")
        log().debug('FAKE write: [%s]'%(ashex(data)))
        # read back written data (as the real bus adapter does)
        o.rdqueue.put(data)
        from .bsb.bsb_telegram import BsbTelegram
        t = BsbTelegram.deserialize(data, o.device)[0]
        
        # remember set value for session
        if t.packettype == 'set':
            log().debug('cached value of %r'%(t.data,))
            o.state[t.field.disp_id] = t.data
            
        t.src, t.dst = t.dst, t.src
        t.packettype = {'set':'ack', 'get':'ret'}[t.packettype]
        
        # for GET, return current state if set, else default value dep. on field type.
        if t.packettype == 'ret':
            try:
                t.data = o.state[t.field.disp_id]
            except KeyError:
                t.data = {
                    'choice': 1,
                    'time': datetime.time(13,37),
                }.get(t.field.type_name, 42)
        rdata = t.serialize(validate=False)
        o.rdqueue.put(rdata)
