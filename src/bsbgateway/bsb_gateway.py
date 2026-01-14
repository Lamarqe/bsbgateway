# -*- coding: utf8 -*-

##############################################################################
#
#    Part of BsbGateway
#    Copyright (C) Johannes Loehnert, 2013-2026
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

import os
#sys.path.append(os.path.dirname(__file__))

import importlib
import logging
from queue import Queue

from .hub.event_sources import SyncedSecondTimerSource
from .single_field_logger import SingleFieldLogger
from .web_interface import WebInterface
from .cmd_interface import CmdInterface
from .bsb.bsb_comm import BsbComm
from . import config_reader

log = lambda: logging.getLogger(__name__)

class BsbGateway(object):
    def __init__(o, gateway_settings, bsbcomm, loggers, cmd_interface=None,web_interface=None):
        o._queue = Queue()
        o._running = False
        o.device = gateway_settings.device
        """Device information object: contains field definitions etc."""

        # Modules
        o._timer = SyncedSecondTimerSource()
        o._bsbcomm = bsbcomm
        o.loggers = loggers
        o.web_interface = web_interface
        o.cmd_interface = cmd_interface
        
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

        # BSB Comm
        o._bsbcomm.bsb_telegrams += _marshal(o.on_bsb_telegrams)
        o._bsbcomm.send_error += _marshal(o.on_send_error)
        o._bsbcomm.start_thread()
        
        if o.cmd_interface:
            o.cmd_interface.quit += _marshal(o.quit)
            o.cmd_interface.send_get += _marshal(o.on_send_get)
            o.cmd_interface.send_set += _marshal(o.on_send_set)
            o.cmd_interface.start_thread()
        else:
            log().info('Running without cmdline interface. Use Ctrl+C or SIGTERM to quit.')
        
        if o.web_interface:
            o.web_interface.web2bsb.send_get += _marshal(o.on_send_get)
            o.web_interface.web2bsb.send_set += _marshal(o.on_send_set)
            o.web_interface.start_thread()

        for logger in o.loggers:
            logger.send_get += _marshal(o.on_send_get)
            # Logger driven by timer tick - no need to start


    def run_eventloop(o):
        """Pull events from the queue and dispatch them.
        
        Stops when o._running flag is cleared.
        """
        o._running = True
        while o._running:
            action = o._queue.get()
            try:
                action()
            except Exception as e:
                log().exception("Internal error: {e}")

    def _dispatch_event(o, evtype, evdata):
            getattr(o, 'on_%s_event'%evtype)(evdata)

    def on_timer_tick(o):
        for logger in o.loggers:
            logger.tick()

    def on_bsb_telegrams(o, telegrams):
        if o.cmd_interface:
            o.cmd_interface.on_bsb_telegrams(telegrams)
        if o.web_interface:
            o.web_interface.web2bsb.on_bsb_telegrams(telegrams)
        for logger in o.loggers:
            logger.on_bsb_telegrams(telegrams)

    def on_send_error(o, error: Exception, disp_id: int, from_address: int):
        if o.cmd_interface:
            o.cmd_interface.on_send_error(error, disp_id, from_address)
        if o.web_interface:
            o.web_interface.web2bsb.on_send_error(error, disp_id, from_address)

    def on_send_get(o, disp_id:int, from_address:int):
        o._bsbcomm.send_get(disp_id, from_address)

    def on_send_set(o, disp_id:int, value, from_address:int, validate:bool=True):
        o._bsbcomm.send_set(disp_id, value, from_address, validate=validate)
                        
    def quit(o):
        o._running = False
        
    def cmdline_set(o, disp_id, value, validate=True):
        o._bsbcomm.send_set(disp_id, value, 1, validate=validate)

def run(config:config_reader.Config):
    try:
        device = importlib.import_module('.bsb.' + config.gateway.device, __package__)
    except ModuleNotFoundError:
        raise ValueError('Unsupported device')
    
    bsbcomm = BsbComm(config.adapter, device)
    
    loggers = SingleFieldLogger.from_config(config.loggers, device)
    if loggers:
        if not os.path.exists(p:=config.loggers.tracefile_dir):
            log().info(f'Creating trace directory {p}')
            os.makedirs(p)

    if config.cmd_interface.enable:
        cmd_interface = CmdInterface(config.cmd_interface, device)
    else:
        cmd_interface = None
    if config.web_interface.enable:
        web_interface = WebInterface(config.web_interface, device) 
    else:
        web_interface = None
                
    BsbGateway(
        gateway_settings=config.gateway,
        bsbcomm=bsbcomm,
        loggers=loggers,
        cmd_interface=cmd_interface,
        web_interface=web_interface,
    ).run()
