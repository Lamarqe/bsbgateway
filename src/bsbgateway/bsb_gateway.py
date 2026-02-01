# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import os
from pathlib import Path
import signal

import logging
from queue import Queue

from .consumer_base import ConsumerBase
from .hub.adapter import get_adapter

from .hub.event_sources import SyncedSecondTimerSource
from .single_field_logger import SingleFieldLogger
from .web_interface import WebInterface
from .cmd_interface import CmdInterface
from .bsb2tcp import Bsb2Tcp
from .bsb.model import BsbModel, set_prefered_language
from .bsb.bsb_comm import BsbComm
from . import config_reader

log = lambda: logging.getLogger(__name__)

class BsbGateway(object):
    """Main class, provides event routing between the modules.

    * adapter: The IO adapter, providing rx_bytes and tx_bytes
    * bsbcomm: (de)serialization of bytes messages.
        * turns rx_bytes into bsb_telegrams events
        * turns send_get/send_set into tx_bytes calls
    * consumers: list of consumer modules.

    The latter three modules are optional. Each of them can send
    get/set requests, and receives bsb_telegrams and send_error events.

    """
    def __init__(o, adapter, bsbcomm, consumers: list[ConsumerBase], bsb2tcp=None):
        o._queue = Queue()
        o._running = False

        # Modules
        o._timer = SyncedSecondTimerSource()
        o._adapter = adapter
        o._bsbcomm = bsbcomm
        o.bsb2tcp = bsb2tcp
        o.consumers = consumers[:]
        
    def run(o):
        o.setup_modules()
        o.run_eventloop()

    def setup_modules(o):
        def _marshal(handler):
            '''makes a handler that puts the action into the main event queue.'''
            def marshaled_handler(*args, **kwargs):
                o._queue.put(lambda: handler(*args, **kwargs))
            return marshaled_handler

        # Timer
        o._timer.tick += _marshal(o.on_timer_tick)
        o._timer.start_thread()

        # Adapter <-> BSB Comm
        o._adapter.rx_bytes += _marshal(o._bsbcomm.rx_bytes)
        o._bsbcomm.tx_bytes += _marshal(o._adapter.tx_bytes)
        o._adapter.start_thread()

        # BSB Comm
        o._bsbcomm.bsb_telegrams += _marshal(o.on_bsb_telegrams)
        o._bsbcomm.send_error += _marshal(o.on_send_error)
        # BSB Comm manages the throttle thread, thus we need to start it here
        o._bsbcomm.start_thread()

        if o.bsb2tcp:
            # BSB2TCP, bypassing BSB Comm (works on bytes level)
            # forward received TCP data to IO Adapter and vice versa
            o.bsb2tcp.rx_bytes += _marshal(o._adapter.tx_bytes)
            o._adapter.rx_bytes += _marshal(o.bsb2tcp.tx_bytes)

            o.bsb2tcp.start()

        has_cmd_interface = False
        for consumer in o.consumers:
            # Consumer modules
            if hasattr(consumer, "send_get"):
                consumer.send_get += _marshal(o.on_send_get)
            if hasattr(consumer, "send_set"):
                consumer.send_set += _marshal(o.on_send_set)
            try:
                consumer.start_thread()
            except Exception as e:
                log().exception(f"Error starting module {consumer}: {e}")
            if isinstance(consumer, CmdInterface):
                has_cmd_interface = True
                consumer.quit += _marshal(o.quit)
        
        if not has_cmd_interface:
            log().info('Running without cmdline interface. Use Ctrl+C or SIGTERM to quit.')

        # Register signal handlers for clean shutdown
        signal.signal(signal.SIGTERM, lambda signum, frame: _marshal(o.quit)("SIGTERM"))
        # SIGINT is handled by KeyboardInterrupt in the event loop
        signal.signal(signal.SIGHUP, lambda signum, frame: _marshal(o.quit)("SIGHUP"))


    def run_eventloop(o):
        """Pull events from the queue and dispatch them.
        
        Stops when o._running flag is cleared.
        """
        o._running = True
        while o._running:
            try:
                action = o._queue.get()
            except KeyboardInterrupt:
                o.quit("Ctrl+C")
                return
            try:
                action()
            except Exception as e:
                log().exception("Internal error: {e}")

    def _dispatch_event(o, evtype, evdata):
            getattr(o, 'on_%s_event'%evtype)(evdata)

    def on_timer_tick(o):
        for consumer in o.consumers:
            try:
                consumer.tick()
            except Exception as e:
                log().exception(f"Error in consumer {consumer}: {e}")

    def on_bsb_telegrams(o, telegrams):
        """Distribute to consumer modules"""
        for consumer in o.consumers:
            try:
                consumer.on_bsb_telegrams(telegrams)
            except Exception as e:
                log().exception(f"Error in consumer {consumer} handling telegrams: {e}")

    def on_send_error(o, error: Exception, disp_id: int, from_address: int):
        """Distribute to consumer modules"""
        for consumer in o.consumers:
            try:
                consumer.on_send_error(error, disp_id, from_address)
            except Exception as e:
                log().exception(f"Error in consumer {consumer} handling send_error: {e}")

    def on_send_get(o, disp_id:int, from_address:int):
        o._bsbcomm.send_get(disp_id, from_address)

    def on_send_set(o, disp_id:int, value, from_address:int, validate:bool=True):
        o._bsbcomm.send_set(disp_id, value, from_address, validate=validate)
                        
    def quit(o, reason="unknown"):
        log().info(f"Shutting down BSB Gateway. Requested by: {reason}")
        if o.bsb2tcp:
            # Not a daemon, must be stopped explicitly
            o.bsb2tcp.stop()
        for consumer in o.consumers:
            try:
                consumer.stop()
            except Exception as e:
                log().exception(f"Error stopping module {consumer}: {e}")
        o._bsbcomm.stop()
        o._adapter.stop()
        o._running = False
        
    def cmdline_set(o, disp_id, value, validate=True):
        o._bsbcomm.send_set(disp_id, value, 1, validate=validate)

def find_model_file(device_name: str) -> Path:
    """Find the model file for the given device name.

    model file name is device name plus .json extension.

    Searches in the current directory, then in ~/.config/bsbgateway, then in /etc/bsbgateway. 

    Returns the path to the model file if found, else raises FileNotFoundError.
    """
    possible_paths = [
        Path(f"{device_name}.json"),
        config_reader.xdg_config_home() / "bsbgateway" / f"{device_name}.json",
        Path(f"/etc/bsbgateway/{device_name}.json"),
    ]
    for path in possible_paths:
        if path.exists() and path.is_file():
            return path
    raise FileNotFoundError(f"'{device_name}.json' not found.")


def run(config:config_reader.Config):
    model_path = find_model_file(config.gateway.device)
    log().info(f'Loading device information from {model_path}')
    model = BsbModel.parse_file(str(model_path))
    set_prefered_language(config.gateway.locale)
    
    # TODO: choose adapter class based on adapter_device setting
    adapter = get_adapter(config.adapter)
    bsbcomm = BsbComm(config.adapter, model)

    if config.bsb2tcp.enable:
        bsb2tcp = Bsb2Tcp(config.bsb2tcp)
    else:
        bsb2tcp = None

    consumers:list[ConsumerBase] = []
    if config.cmd_interface.enable:
        consumers.append(CmdInterface(config.cmd_interface, model))
    if config.web_interface.enable:
        consumers.append( WebInterface(config.web_interface, model))
    loggers = SingleFieldLogger.from_config(config.loggers, model)
    if loggers:
        if not os.path.exists(p:=config.loggers.tracefile_dir):
            log().info(f'Creating trace directory {p}')
            os.makedirs(p)
        consumers.extend(loggers)
                
    BsbGateway(
        adapter=adapter,
        bsbcomm=bsbcomm,
        consumers=consumers,
        bsb2tcp=bsb2tcp,
    ).run()
