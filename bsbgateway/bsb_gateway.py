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
import time

from .hub.event_sources import SyncedSecondTimerSource
from .single_field_logger import SingleFieldLogger
from .web_interface import WebInterface
from .cmd_interface import CmdInterface
from .email_action import make_email_action
from .bsb.bsb_comm import BsbComm

log = lambda: logging.getLogger(__name__)


class BsbGateway(object):
    def __init__(o, bsbcomm, device, loggers, cmd_interface=None,web_interface=None):
        o._queue = Queue()
        o._running = False
        o.device = device
        """Device information object: contains field definitions etc."""

        # Modules
        o._timer = SyncedSecondTimerSource()
        o._bsbcomm = bsbcomm
        o.loggers = loggers
        o.web_interface = web_interface
        o.cmd_interface = cmd_interface
        
    def run(o):
        log().info('BsbGateway (c) J. Loehnert 2013-2026, starting @%s'%time.time())
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

def run(config):
    try:
        device = importlib.import_module('.bsb.' + config['device'], __package__)
    except ModuleNotFoundError:
        device = None
    if not device:
        raise ValueError('Unsupported device')
    
    emailaction = make_email_action(config['emailserver'], config['emailaddress'], config['emailcredentials'])

    bsbcomm = BsbComm(config['adapter_settings'], device, min_wait_s=config.get('min_wait_s', 0.1))
    
    if config['loggers']:
        if not os.path.exists(config['tracefile_dir']):
            log().info('Creating trace directory %s'%config['tracefile_dir'])
            os.makedirs(config['tracefile_dir'])
    loggers = [
        SingleFieldLogger(
            field=device.fields[disp_id],
            interval=interval, 
            atomic_interval=config['atomic_interval'],
            filename=os.path.join(config['tracefile_dir'], '%d.trace'%disp_id),
            bsb_address=config['logger_bus_address'],
        ) 
        for disp_id, interval in config['loggers']
    ]
    if config["cmd_interface_enable"]:
        cmd_interface = CmdInterface(device, bsb_address=config['cmdline_bus_address'])
    else:
        cmd_interface = None
    if config["web_interface_enable"]:
        web_interface = WebInterface(
            device=device, 
            bsb_address=config['webinterface_bus_address'],
            port=config["web_interface_port"], 
            dashboard=config.get('web_dashboard', [])
        ) 
    else:
        web_interface = None
    for trigger in config['triggers']:
        disp_id = trigger[0]
        for logger in loggers:
            if logger.field.disp_id == disp_id:
                logger.add_trigger(emailaction, *trigger[1:])
    # legacy config
    tt = config["adapter_settings"].pop("adapter_type", "")
    if tt == "fake":
        config["adapter_settings"]["adapter_device"] = ":sim"
                
    BsbGateway(
        bsbcomm=bsbcomm,
        device=device,
        loggers=loggers,
        cmd_interface=cmd_interface,
        web_interface=web_interface,
    ).run()
