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

import logging
import dataclasses as dc

from contextlib import contextmanager
import threading
import queue
import time

# FIXME: importing from parent, this smells bad
from bsbgateway.hub.event_sources import EventSource
from bsbgateway.hub.event import event
from bsbgateway.hub.serial_source import SerialSource

from .bsb_telegram import BsbTelegram
from .bsb_field import ValidateError, EncodeError

log = lambda: logging.getLogger(__name__)

MAX_PENDING_REQUESTS = 50

@dc.dataclass
class AdapterSettings:
    """Settings for the IO adapter used to connect to the BSB bus.
    
    Hardware settings are ignored when using simulation."""
    adapter_device: str = "/dev/ttyUSB0"
    """The device name of the serial adapter.

    * '/dev/ttyS0' ... '/dev/ttyS3' are usual devices for real serial ports.
    * '/dev/ttyUSB0' is the usual device for a USB-to-serial converter on Linux.
    * ':sim' opens a simple device simulation (no actual serial port required)
    """
    port_baud: int = 4800
    """Baudrate - typical value for BSB bus is 4800."""
    port_stopbits: float = 1
    """Stopbits - 1, 1.5 or 2. For BSB bus, use 1."""
    port_parity: str = 'odd'
    """Parity - 'none', 'odd' or 'even'. For BSB bus, use 'odd' if you invert bytes, "even" if not."""
    invert_bytes: bool = True
    """Invert all bits after receive + before send?
    
    If you use a simple BSB-to-UART level converter, you most probably need to
    set this to True.
    """
    expect_cts_state: bool | None = None
    """Only send if CTS has this state (True or False); None to disable.

    Use this if your adapter has a "bus in use" detection wired to CTS pin of
    the RS232 interface.
    """
    write_retry_time: float = 0.005
    """Wait time in seconds if blocked by CTS (see above)."""
    min_wait_s: float = 0.1
    """Minimum wait time between subsequent data requests on the bus.

    Used to avoid blocking up the bus when lots of requests come in at once. In case of contention, the oldest requests are dropped.

    Note that the web interface has builtin timeout of 3.0 s. I.e. if you send
    more than (3.0 / min_wait_s) requests at once, data will be lost.
    """

class BsbComm(EventSource):
    '''simplifies the conversion between serial data and BsbTelegrams.
    BsbComm represents one or multiple BSB bus endpoint(s). You can
    send and receive BsbTelegrams. 
    
    Wrapper around the serial source: instead of raw data,
    the parsed telegrams are returned. Event payload is a list of BsbTelegrams.
    '''
    bus_addresses = []
    _leftover_data = b''
    
    def __init__(o, adapter_settings:AdapterSettings, device):
        o.serial = SerialSource(
            port_num=adapter_settings.adapter_device,
            # use sane default values for the rest if not set
            port_baud=adapter_settings.port_baud,
            port_stopbits=adapter_settings.port_stopbits,
            port_parity=adapter_settings.port_parity,
            # Most simple RS232 level converters will deliver inverted bytes.
            invert_bytes=adapter_settings.invert_bytes,
            expect_cts_state=adapter_settings.expect_cts_state,
            write_retry_time=adapter_settings.write_retry_time,
        )
        o.device = device
        o._leftover_data = b''
        o.min_wait_s = adapter_settings.min_wait_s
        o._do_throttled = None
        
    @event
    def bsb_telegrams(telegrams:list[BsbTelegram]):
        '''Emitted when telegrams are received from BSB bus.
        
        Payload is a list of BsbTelegrams instances.
        '''

    @event
    def send_error(error:Exception, disp_id:int, from_address:int):
        '''Emitted when sending a telegram failed.
        
        Payload is (error, disp_id, from_address).

        Errors might occur due to validation errors, encoding errors or failed IO.
        '''

    def run(o):
        def convert_data(timestamp, data):
            telegrams = o.process_received_data(timestamp, data)
            o.bsb_telegrams(telegrams)
        o.serial.data += convert_data
        with throttle_factory(min_wait_s=o.min_wait_s) as do_throttled:
            o._do_throttled = do_throttled
            o.serial.run()
        o._do_throttled = None
        
    def process_received_data(o, timestamp, data) -> list[BsbTelegram]:
        '''timestamp: unix timestamp
        data: incoming data (byte string) from the serial port
        return list of (which_address, telegram)
        if promiscuous=True:
            all telegrams are returned. Telegrams not for me get which_address=None.
        else:
            Only telegrams that have the right bus address and packettype 7 (return value)
            are included in the result.
        '''
        telegrams = BsbTelegram.deserialize(o._leftover_data + data, o.device)
        result = []
        if not telegrams:
            return result
        # junk at the end? remember, it could be an incomplete telegram.
        leftover = b''
        for data in reversed(telegrams):
            if isinstance(data, BsbTelegram):
                break
            leftover = data[0] + leftover
        o._leftover_data = leftover

        for t in telegrams:
            if isinstance(t, BsbTelegram):
                t.timestamp = timestamp
                result.append(t)
            elif t[1] != 'incomplete telegram':
                log().info('++++%r :: %s'%t )
        return result

    def send_get(o, disp_id, from_address):
        '''sends a GET request for the given disp_id.
        which_address: which busadress to use, default 0 (the first)'''
        if disp_id not in o.device.fields:
            raise EncodeError('unknown field')
        t = BsbTelegram()
        t.src = from_address
        t.dst = 0
        t.packettype = 'get'
        t.field = o.device.fields[disp_id]
        try:
            o._send_throttled(t.serialize())
        except (ValidateError, EncodeError, IOError) as e:
            o.send_error(e, disp_id, from_address)

    def send_set(o, disp_id, value, from_address, validate=True):
        '''sends a SET request for the given disp_id.
        value is a python value which must be appropriate for the field's type.
        which_address: which busadress to use, default 0 (the first).
        validate: to disable validation, USE WITH EXTREME CARE.
        '''
        if disp_id not in o.device.fields:
            raise EncodeError('unknown field')
        t = BsbTelegram()
        t.src = from_address
        t.dst = 0
        t.packettype = 'set'
        t.field = o.device.fields[disp_id]
        t.data = value
        # might throw ValidateError or EncodeError.
        try:
            data = t.serialize(validate=validate)
            o._send_throttled(data)
        except (ValidateError, EncodeError, IOError) as e:
            o.send_error(e, disp_id, from_address)

    def _send_throttled(o, data:bytes):
        if not o._do_throttled:
            raise IOError("Cannot send: Not running")
        o._do_throttled(lambda: o.serial.write(data))
        

@contextmanager
def throttle_factory(min_wait_s = 0.1, max_pending_requests=MAX_PENDING_REQUESTS):
    """Throttled action.

    Contextmanager yields a function ``do_throttled(action)``.

    Calling it will schedule a call of ``action()``, which can be whatever you want..

    Multiple action(s) are executed sequentially, and there is a minimum time of
    ``min_wait_s`` between *end* of last and *start* of next action.

    To achieve this, a separate thread is used, which is automatically started
    and stopped.
    """
    stop = threading.Event()
    todo:queue.Queue = queue.Queue(maxsize=max_pending_requests)

    def runner():
        action = None
        while not stop.is_set():
            if action is not None:
                try:
                    action()
                except Exception:
                    log().error("Exception in throttle thread", exc_info=True)
            action_end_time = time.time()
            action = todo.get()
            # Throttle using wallclock time
            # If todo.get() blocked for longer than min_wait_s, do not wait.
            wait_for = action_end_time + min_wait_s - time.time()
            if wait_for > 0.0:
                log().debug("throttle: wait %s seconds", wait_for)
                stop.wait(wait_for)

    def do_throttled(action):
        try:
            todo.put(action, timeout=0)
        except queue.Full as e:
            raise RuntimeError("Too many requests at once!") from e

    thread = threading.Thread(target=runner, name="throttled_runner")
    thread.start()
    try:
        yield do_throttled
    finally:
        stop.set()
        # Unblock todo.get()
        todo.put(lambda:None)
