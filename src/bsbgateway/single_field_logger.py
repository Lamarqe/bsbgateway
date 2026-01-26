# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import time
import os
import dataclasses as dc

from bsbgateway.bsb.model import BsbCommand, BsbDatatype, BsbModel, BsbType
from bsbgateway.hub.event import event

@dc.dataclass
class LoggerConfig:
    """Single field loggers.
    
    Loggers will request and log the configured fields at the specified intervals.

    If no fields are configured (field_disp_ids is empty list), logging is disabled.
    """
    field_disp_ids: list[int] = dc.field(default_factory=lambda: [])
    """List of field display IDs (4-digit ids) to log."""
    intervals: list[int] = dc.field(default_factory=lambda: [])
    """List of logging intervals (in seconds) for each field."""
    tracefile_dir: str = 'traces'
    """Directory to store trace files in.
    
    If you run as system service, use an absolute path like
    /var/log/bsbgateway/traces, and make sure that the user has write access.
    """
    bsb_address: int = 23
    """Bus address of the BSB device to log from."""

    @property
    def enable(o) -> bool:
        """Whether logging is enabled (i.e., any fields are configured)."""
        return len(o.field_disp_ids) > 0


class SingleFieldLogger:
    _last_save_time = 0
    _last_saved_value = None
    _dtype:BsbType|None = None
    _last_was_value = False
    
    def __init__(o, field:BsbCommand, interval=1, atomic_interval=1, filename='', bsb_address=23):
        o.field:BsbCommand = field
        o.interval = interval
        o.atomic_interval = atomic_interval
        o.bsb_address = bsb_address
        # list of fn(prev_val, this_val)
        o.triggers = []
        # list of timestamps when trigger was last fired.
        o.trigger_timestamps = []
        o.putevent_func = lambda evname, evdata: None
        
        o.filename = filename or '%d.trace'%o.field.disp_id
        if not os.path.exists(filename):
            o.log_fieldname()
        o.log_interval()

    @classmethod
    def from_config(cls, config:LoggerConfig, device:BsbModel) -> list['SingleFieldLogger']:
        """Create loggers from configuration."""
        loggers = []
        for disp_id, interval in zip(config.field_disp_ids, config.intervals):
            field = device.fields.get(disp_id, None)
            if not field:
                raise ValueError(f'Field with display ID {disp_id} not found for device {device.name}')
            logger = cls(
                field=field,
                interval=interval,
                atomic_interval=1,
                filename=os.path.join(config.tracefile_dir, f'{disp_id}.trace'),
                bsb_address=config.bsb_address,
            )
            loggers.append(logger)
        return loggers
    
    @event
    def send_get(disp_id:int, from_address:int): # type:ignore
        """Request to get the field value from BSB device.
        """
        
    def add_trigger(o, callback, triggertype, param1=None, param2=None):
        '''callback: void fn()
        '''
        def fire_trigger(prev_val, this_val):
            callback(logger=o, 
                     triggertype=triggertype, 
                     param1=param1, 
                     param2=param2, 
                     prev_val=prev_val, 
                     this_val=this_val
            )
        
        if triggertype == 'rising_edge':
            def trigger(prev_val, this_val):
                if prev_val<=param1 and this_val>param1:
                    fire_trigger(prev_val, this_val)
                    return True
                return False
        elif triggertype == 'falling_edge':
            def trigger(prev_val, this_val):
                if prev_val>=param1 and this_val<param1:
                    fire_trigger(prev_val, this_val)
                    return True
                return False
        else:
            raise ValueError('bad trigger type %s'%triggertype)
        o.triggers.append(trigger)
        o.trigger_timestamps.append(0)
        
    def check_triggers(o, timestamp, prev_val, this_val):
        for n in range(len(o.triggers)):
            # dead time of 6 hrs after each trigger event!
            if timestamp >= 6*3600 + o.trigger_timestamps[n]:
                # trigger function returns True if trigger fired
                if o.triggers[n](prev_val, this_val):
                    o.trigger_timestamps[n] = timestamp
        
    def get_now(o):
        return o.atomic_interval * int(time.time() / o.atomic_interval)
        
    def tick(o):
        if int(time.time()) % o.atomic_interval!=0:
            return
        t = o.get_now()
        if t % o.interval == 0:
            o.send_get(o.field.disp_id, o.bsb_address)

    def on_bsb_telegrams(o, telegrams):
        for  telegram in telegrams:
            if telegram.dst==o.bsb_address and telegram.packettype=="ret":
                if o.field.disp_id == telegram.field.disp_id:
                    o.log_value(telegram.timestamp, telegram.data)
            
    def log_value(o, timestamp, value):
        t = o.atomic_interval * int(timestamp  / o.atomic_interval)
        if t != o._last_save_time + o.interval:
            o.log_new_timestamp(t)
        else:
            o._last_save_time = t
            if o._last_saved_value is not None:
                o.check_triggers(t, o._last_saved_value, value)
        if o._last_saved_value is not None and value == o._last_saved_value:
            o._log_append('~', False)
        else:
            dtype = o.field.type
            if dtype is None:
                raise ValueError('Field %s has no type informtaion'%o.field.disp_name)
            if dtype != o._dtype:
                o._log_append(':dtype %s'%dtype.name)
                o._dtype = dtype
            o._log_append('%s'%_serialize_value(value, dtype))
        o._last_saved_value = value
            
    def log_fieldname(o):
        o._log_append(':disp_id %d'%o.field.disp_id)
        o._log_append(':fieldname %s'%o.field.disp_name)
        
    def log_interval(o):
        o._log_append(':interval %d'%o.interval)
            
    def log_new_timestamp(o, timestamp):
        o._log_append(':time %d'%timestamp)
        o._last_save_time = timestamp
    
    def _log_append(o, txt, linebreak_before=True):
        fh = open(o.filename, 'a')
        if linebreak_before or not o._last_was_value:
            txt = '\n'+txt
        fh.write(txt)
        fh.close()
        o._last_was_value = not (txt.startswith(':') or txt.startswith('\n:'))
        
def _serialize_value(val, dtype:BsbType):
    if val is None:
        return '--'
    datatype = dtype.datatype
    if datatype == BsbDatatype.Raw:
        # unknown field type, save raw hex code
        return ' '.join('%02X'%b for b in val)
    elif datatype in [
        BsbDatatype.Vals,
        BsbDatatype.Enum,
        BsbDatatype.Bits,
    ] or dtype.name.lower() == 'year':
        return '%g'%val
    elif datatype == BsbDatatype.String:
        return str(val)
    elif datatype == BsbDatatype.Datetime:
        return val.strftime('%Y-%m-%d %H:%M:%S')
    elif datatype == BsbDatatype.DayMonth:
        return val.strftime('%d.%m.')
    elif datatype == BsbDatatype.Time:
        return val.strftime('%H:%M:%S')
    elif datatype == BsbDatatype.HourMinutes:
        return val.strftime('%H:%M')
    else:
        # missing bsb types:
        # TimeProgram
        # Date
        raise ValueError('Cannot save values of type %s'%dtype)