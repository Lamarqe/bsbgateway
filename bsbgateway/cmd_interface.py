# -*- coding: utf8 -*-

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

import re
import datetime
import logging

from bsbgateway.bsb.bsb_telegram import BsbTelegram
from bsbgateway.hub.event import event

from .hub.event_sources import EventSource, StdinSource
from .bsb.bsb_field import ValidateError, EncodeError

log = lambda: logging.getLogger(__name__)

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
        're': r's(et)?\s+(?P<disp_id>[0-9]+)\s(?P<value>[0-9.:-]+)\s*(?P<use_force>[!]?)',
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
    def __init__(o, device, bsb_address=24):
        o.device = device
        o.bsb_address = bsb_address
        o.stdin_source = StdinSource()
        o.stdin_source.line += o.on_stdin_event
        # This is eval'd, so use text string.
        o._dump_filter = 'False'
    
    @event
    def quit():
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
        o.quit()
                        
    def cmd_get(o, disp_id):
        disp_id = int(disp_id)
        try:
            o.send_get(disp_id, o.bsb_address)
        except (ValidateError, EncodeError) as e:
            print(e.__class__.__name__ +': '+ str(e))
        
                        
    def cmd_set(o, disp_id, value, use_force):
        try:
            disp_id = int(disp_id)
            field = o.device.fields[disp_id]
        except (TypeError, ValueError, KeyError):
            print('Unrecognized field.')
            return
        if value == '--':
            value = None
        else:
            try:
                if field.type_name in ['choice', 'int8']:
                    value = int(value)
                elif field.type_name in ['int16', 'temperature', 'int32']:
                    value = float(value)
                elif field.type_name in ['time']:
                    value = datetime.time(*map(int, value.split(':')))
                else:
                    raise TypeError('Data type for field %s %s is not defined.'%(field.disp_id, field.disp_name))
            except (TypeError, ValueError) as e:
                print(e)
                return
        try:
            # TOOD: put as event
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
            grps = [grp
                    for grp in o.device.groups
                    if text in grp.name.lower()
            ]
        else:
            grps = o.device.groups
        if len(grps) == 0:
            print('Not found.')
            return
        # expand if searching in field names or if only one group was found.
        if (text and not hash) or len(grps)==1:
            expand = True
            
        for grp in grps:
            if not expand:
                print('#'+grp.name)
            else:
                flds = grp.fields
                if text and not hash:
                    flds = [f for f in flds if text in f.disp_name.lower()]
                flds.sort(key=lambda x: (x.disp_id, x.telegram_id))
                if flds:
                    print('#'+grp.name+':')
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
        ll.sort(key=lambda x: (x.disp_id, x.telegram_id))
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
            print(repr(telegram))
