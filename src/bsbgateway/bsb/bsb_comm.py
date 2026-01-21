# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import logging
import dataclasses as dc

from contextlib import contextmanager
import threading
import queue
import time

# FIXME: importing from parent, this smells bad
from bsbgateway.hub.adapter_settings import AdapterSettings
from bsbgateway.hub.event_sources import EventSource
from bsbgateway.hub.event import event

from .model import BsbModel
from .bsb_telegram import BsbTelegram
from .errors import ValidateError, EncodeError

log = lambda: logging.getLogger(__name__)

MAX_PENDING_REQUESTS = 50

class BsbComm(EventSource):
    '''simplifies the conversion between serial data and BsbTelegrams.
    BsbComm represents one or multiple BSB bus endpoint(s). You can
    send and receive BsbTelegrams. 
    
    Wrapper around the serial source: instead of raw data,
    the parsed telegrams are returned. Event payload is a list of BsbTelegrams.
    '''
    bus_addresses = []
    _leftover_data = b''
    
    def __init__(o, adapter_settings:AdapterSettings, device:BsbModel):
        o.device:BsbModel = device
        o._leftover_data = b''
        o.min_wait_s = adapter_settings.min_wait_s
        with throttle_factory(min_wait_s=o.min_wait_s) as do_throttled:
            o._do_throttled = do_throttled
        
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

    @event
    def tx_bytes(data:bytes):
        '''Emitted to request bytes to be sent to the IO adapter.'''

    def run(o):
        with throttle_factory(min_wait_s=o.min_wait_s) as do_throttled:
            o._do_throttled = do_throttled
            # block here until context is exited
            while o._running:
                time.sleep(1)
        o._do_throttled = None
        
    def rx_bytes(o, data:bytes):
        '''data: incoming data (byte string) from the adapter

        Triggers bsb_telegrams with the converted result.
        '''
        telegrams = o.process_received_data(data)
        o.bsb_telegrams(telegrams)

    def process_received_data(o, data) -> list[BsbTelegram]:
        '''data: incoming data (byte string) from the adapter
        return list of (which_address, telegram)
        if promiscuous=True:
            all telegrams are returned. Telegrams not for me get which_address=None.
        else:
            Only telegrams that have the right bus address and packettype 7 (return value)
            are included in the result.
        '''
        timestamp = time.time()
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
        t = BsbTelegram(
            command = o.device.fields[disp_id],
            src = from_address,
            dst = 0,
            packettype = 'get'
        )
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
        t = BsbTelegram(
            command = o.device.fields[disp_id],
            src = from_address,
            dst = 0,
            packettype = 'set',
            data = value
        )
        # might throw ValidateError or EncodeError.
        try:
            data = t.serialize(validate=validate)
            o._send_throttled(data)
        except (ValidateError, EncodeError, IOError) as e:
            o.send_error(e, disp_id, from_address)

    def _send_throttled(o, data:bytes):
        if not o._do_throttled:
            raise IOError("Cannot send: Not running")
        o._do_throttled(lambda: o.tx_bytes(data))
        

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
        if todo.full():
            _ = todo.get()
            log().warning("Device request queue full. Dropping oldest message from outbox.")
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
