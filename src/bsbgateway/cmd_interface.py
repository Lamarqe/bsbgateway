# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import re
import datetime
import logging
import dataclasses as dc

from bsbgateway.bsb.bsb_telegram import BsbTelegram
from bsbgateway.bsb.model import BsbCommand, BsbDatatype, BsbModel, ScheduleEntry
from bsbgateway.hub.event import event

from .hub.event_sources import EventSource, StdinSource
from .bsb.bsb_field import ValidateError, EncodeError

log = lambda: logging.getLogger(__name__)

@dc.dataclass
class CmdInterfaceConfig:
    """Commandline interface settings."""
    enable: bool = True
    """Enable command line interface."""
    bsb_address: int = 24
    """Bus address of the command line interface module."""

CMDS = [
    {
        'cmd': 'quit',
        're': r'q(uit)?',
        'help': 'quit - what it says',
    }, {
        'cmd': 'help',
        're': r'h(elp)?(\s+(?P<cmd>[a-z]+))?',
        'help': 'help [<cmd>] - help on specific command, without cmd = this message'
    }, {
        'cmd': 'get',
        're': r'g(et)?\s+(?P<disp_id>[0-9]+)',
        'help': '''get <field> - request value of field with ID <field> once (without logging)
            field id = the value as seen on the standard LCD display.
        ''',
    }, {
        'cmd': 'set',
        're': r's(et)?\s+(?P<disp_id>[0-9]+)\s(?P<value>[T0-9.,;:-]+)\s*(?P<use_force>[!]?)',
        'help': '''set <field> <value>[!]- set value of field with ID <field>.
            field id = the value as seen on the standard LCD display.
            value = 
                    | number e.g. "0", "1.1", "-5"
                    | time e.g. "08:30"
                    | choice index e.g. "2"
                    | "--" (not set)
                (each time without quotes) depending on field.
            "!" after the value disables validation (bounds checking). USE AT YOUR OWN RISK.
        ''',
    }, {
        'cmd': 'dump',
        're': r'd(ump)?\s*(?P<expr>.*)',
        'help': '''dump [<expr>] - dump received data matching the filter.
            <expr> is a python expression* which can combine the following variables:
                src - source bus address ex. src=10
                dst - destination bus address ex. dst=0
                field - disp id of field ex. field=8510
                fieldhex - hex (bus visible) id of field ex. fieldhex=0x493d052a
                type - ret, get, set, ack, inf ex. type=ack
            ... and must return True or False.
            "dump off" = dump nothing
            "dump on" = dump everything that goes over the bus
            without argument, toggle between on and off.
            
            notes:
                * in the expression you can use = instead of == for comparison.
                
            examples:
                "dump type=ret" dumps all return telegrams (answer to get)
                "dump field=8510" dumps all telegrams concerning that field
                "dump dst=10 or src=10" dumps all tel. from+to address 10
        '''
    }, {
        'cmd': 'list',
        're': r'l(ist)?\s*(?P<hash>#)?(?P<text>[^+]*)(?P<expand>\+)?',
        'help': '''list [#][<text>][+]: list field groups.
            list:
                lists all known groups (menus)
            list #<text>:
                lists all groups (menus) containing the text. If only a single group matches, lists its fields.
            list <text>:
                lists all fields whose name contains the text.
            list+ or list #<text>+: forces expanded view (include field lists).
'''
    }, {
        'cmd': 'info',
        're': r'i(nfo)?\s*?(?P<ids>[0-9 ]+)?',
        'help': '''info <id>[ <id>...]: print field descriptions for the given field ids (4-digit numbers).
'''
    }
]

class CmdInterface(EventSource):
    def __init__(o, config:CmdInterfaceConfig, device:BsbModel):
        o.device:BsbModel = device
        o.bsb_address = config.bsb_address
        o.stdin_source = StdinSource()
        o.stdin_source.line += o.on_stdin_event
        # This is eval'd, so use text string.
        o._dump_filter = 'False'
    
    @event
    def quit(reason:str):
        """Request to quit the gateway."""

    @event
    def send_get(disp_id: int, from_address: int): #type: ignore
        """Request to get a field value from BSB device."""

    @event
    def send_set(disp_id: int, value, from_address: int, validate: bool): #type: ignore
        """Request to set a field value on BSB device."""


    def run(o):
        o.cmd_help()
        o.stdin_source.run()
        
    def on_stdin_event(o, line):
        line = line[:-1] # crop newline
        if not line.strip():
            return
        for cmd in CMDS:
            m = re.match(cmd['re'], line, re.I)
            if m:
                # call o.cmd_whatever with named groups as kwargs
                try:
                    getattr(o, 'cmd_' + cmd['cmd'])(**m.groupdict())
                except Exception as e:
                    log().exception('Something crashed while processing this command.')
                    print('Error: '+str(e))
                break
        else:
            print('Unrecognized command:', repr(line))

    def on_bsb_telegrams(o, telegrams: list[BsbTelegram]):
        for telegram in telegrams:
            o.filtered_print(telegram)

    def on_send_error(o, error: Exception, disp_id: int, from_address: int):
        if from_address == o.bsb_address:
            print('Error sending to field %d: %s'%(disp_id, str(error)))
        
    def cmd_quit(o):
        o.quit("CLI command")
                        
    def cmd_get(o, disp_id: int):
        disp_id = int(disp_id)
        try:
            o.send_get(disp_id, o.bsb_address)
        except (ValidateError, EncodeError) as e:
            print(e.__class__.__name__ +': '+ str(e))
        
                        
    def cmd_set(o, disp_id: int, value, use_force: str):
        try:
            disp_id = int(disp_id)
            field:BsbCommand = o.device.fields[disp_id]
        except (TypeError, ValueError, KeyError):
            print('Unrecognized field.')
            return
        if field.type is None:
            print('Field is missing its type definition.')
            return
        if value == '--':
            value = None
        else:
            try:
                match field.type.datatype:
                    case BsbDatatype.Vals:
                        try:
                            value = int(value)
                        except ValueError:
                            value = float(value)
                    case BsbDatatype.Enum | BsbDatatype.Bits:
                        value = int(value)
                    case BsbDatatype.String:
                        value = str(value)
                    case BsbDatatype.Datetime:
                        value = datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
                    case BsbDatatype.DayMonth:
                        value = datetime.datetime.strptime(value, '%m-%d').date()
                    case BsbDatatype.Time:
                        value = datetime.datetime.strptime(value, '%H:%M:%S').time()
                    case BsbDatatype.HourMinutes:
                        value = datetime.datetime.strptime(value, '%H:%M').time()
                    case BsbDatatype.TimeProgram:
                        pairs = value.split(';')
                        entries = []
                        for p in pairs:
                            t1, t2 = p.split('-')
                            time1 = datetime.datetime.strptime(t1, '%H:%M').time()
                            time2 = datetime.datetime.strptime(t2, '%H:%M').time()
                            entries.append( ScheduleEntry(time1, time2) )
                        value = entries
                    case _:
                        raise TypeError('Data type for command %s %s is not defined.'%(field.telegram_id, field.disp_name))
            except (TypeError, ValueError) as e:
                print(e)
                return
        try:
            validate=(use_force!='!')
            o.send_set(disp_id, value, o.bsb_address, validate)
        except (ValidateError, EncodeError) as e:
            print(e.__class__.__name__ +': '+ str(e))
            
    def cmd_dump(o, expr=None):
        # switch: Off if any filter is set, else On
        if expr is None or expr == '':
            expr = 'on' if o._dump_filter == 'False' else 'off'
            
        if expr == 'off':
            o._dump_filter = 'False'
            print('dump is now off.')
            log().debug('dump filter: %r'%o._dump_filter)
            return
        if expr == 'on':
            expr = 'True'
        expr = expr.replace('=', '==')
        expr = expr.replace('>==', '>=').replace('<==', '<=')
        
        try:
            x = eval(expr, {}, {
                'src':0, 'dst':0, 'field':0, 'fieldhex':0, 'type':0,
                'inf':'inf', 'ret':'ret', 'get':'get', 'ack':'ack', 'set':'set'
            })
        except:
            print('bad filter expression')
            return
        print('dump is now on.')
        o._dump_filter = expr
        log().debug('dump filter: %r'%o._dump_filter)
        
    def cmd_list(o, text='', hash='', expand=''):
        '''list [<text>][+]: list field groups.
            list:
                lists all known groups (menus)
            list #<text>:
                lists all groups (menus) containing the text. If only a single group matches, lists its fields.
            list <text>:
                lists all fields whose name contains the text.
            list+ or list #<text>+: forces expanded view (include field lists).
'''
        hash = bool(hash)
        expand = bool(expand)
        text = text.lower()
        if not text: hash=True
        if hash:
            grps = [category
                    for category in o.device.categories.values()
                    if text in category.name.de.lower()
            ]
        else:
            grps = list(o.device.categories.values())
        if len(grps) == 0:
            print('Not found.')
            return
        # expand if searching in field names or if only one group was found.
        if (text and not hash) or len(grps)==1:
            expand = True
            
        for grp in grps:
            if not expand:
                print('#'+grp.name.de)
            else:
                flds = grp.commands
                if text and not hash:
                    flds = [f for f in flds if text in f.disp_name.lower()]
                flds.sort(key=lambda x: (x.parameter, x.telegram_id))
                if flds:
                    print('#'+grp.name.de+':')
                    for f in flds:
                        print('    '+f.short_description)
                    print()
            
    def cmd_info(o, ids=''):
        '''info <id>[, <id>...]: print field descriptions for the given field ids (4-digit numbers).'''
        ids = [int(id) for id in ids.split(' ') if id!='']
        try:
            ll = [o.device.fields[id] for id in ids]
        except KeyError:
            print('Not found.')
            return
        ll.sort(key=lambda x: (x.parameter, x.telegram_id))
        for field in ll:
            print(field.long_description)
            print()

    def cmd_help(o, cmd=''):
        if not cmd:
            print('''BsbGateway (c) 2013-2015 J. Löhnert
Commands: (every command can be abbreviated to just the first character)
    
%s

'''%(
                '\n'.join((cmd['help'].split('\n')[0] for cmd in CMDS)),
            ))
        else:
            cmd = [c for c in CMDS if c['cmd'].startswith(cmd)]
            if not cmd:
                print('Unknown command.')
            else:
                print(cmd[0]['help'])
                
        
    def filtered_print(o, telegram):
        log().debug('applying filter to %r'%telegram)
        try:
            ff = eval(o._dump_filter, {}, {
                'src':telegram.src, 'dst':telegram.dst, 'type': telegram.packettype,
                'field': telegram.field.disp_id, 'fieldhex': telegram.field.telegram_id,
                'inf':'inf', 'get':'get', 'ret':'ret', 'set':'set', 'ack':'ack'
            })
        except Exception as e:
            log().error('error applying filter: %r'%e)
            ff = False
        if telegram.dst==o.bsb_address or ff is True:
            print(str(telegram))
