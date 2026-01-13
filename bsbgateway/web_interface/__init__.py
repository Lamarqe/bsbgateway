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

import web
from queue import Queue

from bsbgateway.bsb.bsb_field import EncodeError, ValidateError
from bsbgateway.hub.event_sources import EventSource
from bsbgateway.hub.event import event
from .config import WebInterfaceConfig
from .index import Index
from .field import Field
from .group import Group

log = lambda: logging.getLogger(__name__)

_HANDLERS = [
    Index,
    Field,
    Group,
]

def add_to_ctx(obj, key):
    '''makes a processor that attaches the given obj to web.ctx as property "key".'''
    def processor(handler):
        setattr(web.ctx, key, obj)
        return handler()
    return processor

def print_handlers(urls):
    s = ["URL Mapping:"]
    for url, cls in zip(urls[::2], urls[1::2]):
        s.append(str(url))
        s.append("  --> "+cls.__module__ + "." + cls.__name__)
        s.append('')
    log().info('\n    '.join(s))

class WebInterface(EventSource):
    def __init__(o, config: WebInterfaceConfig, device):
        o.device = device
        o.web2bsb = Web2Bsb(device, bsb_address=config.bsb_address)

        o.port = config.port
        dash_fields = []
        dash_breaks = []
        n = 0
        for row in config.web_dashboard or []:
            if not row:
                continue
            dash_breaks.append(n)
            for disp_id in row:
                n += 1
                dash_fields.append(device.fields_by_disp_id[disp_id] if disp_id else None)
        o.dash_fields = dash_fields
        o.dash_breaks = dash_breaks[1:]
        o.stoppable = False
        o.server = None

    def run(o):
        urls = []
        for cls in _HANDLERS:
            urls.append('/' + cls.url)
            urls.append(cls)
            
        print_handlers(urls)
        
        app = web.application(urls)
        app.add_processor(add_to_ctx(o.web2bsb, 'bsb'))
        app.add_processor(add_to_ctx(o.dash_fields, "dash_fields"))
        app.add_processor(add_to_ctx(o.dash_breaks, "dash_breaks"))
        #web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", o.port)) 
        o.server = o.startserver(app.wsgifunc(), o.port)
        
    def startserver(o, func, port):
        from web.httpserver import WSGIServer, StaticMiddleware
        func = StaticMiddleware(func)
        func = MyLogMiddleware(func)
    
        o.server = WSGIServer(("0.0.0.0", port), func)

        log().info("Web interface listening on http://0.0.0.0:%d/" % port)

        o.server.start()
        
    def stop(o):
        if o.server:
            o.server.stop()
            o.server = None


class Web2Bsb(object):
    '''provides the connection from web to backend.'''
    def __init__(o, device, bsb_address=25):
        o.device = device
        o.bsb_address = bsb_address
        o.pending_web_requests = []

    @property
    def fields(o):
        return o.device.fields
    
    @property
    def groups(o):
        return o.device.groups

    @event
    def send_get(disp_id:str, from_address:int): # type:ignore
        """Request to get a field value from BSB device.
        
        disp_id: display id of the field to get.
        bsb_address: address to use on the BSB bus.
        """

    @event
    def send_set(disp_id:str, value, from_address:int, validate:bool): # type:ignore
        """Request to set a field value on BSB device.
        
        disp_id: display id of the field to set.
        value: string representation of the value to set.
        bsb_address: address to use on the BSB bus.
        """
        
    def get(o, disp_id:int):
        """called by web handlers to get a field value from BSB device."""
        rq = Queue()
        o._bsb_send(rq, 'get', disp_id)
        return rq
        
    def set(o, disp_id:int, value:str):
        """called by web handlers to set a field value on BSB device."""
        rq = Queue()
        o._bsb_send(rq, 'set', disp_id, value)
        return rq

    def _bsb_send(o, rq, action, disp_id, value=None):
        if action == 'get':
            o.pending_web_requests.append(('ret%d'%disp_id, rq))
            o.send_get(disp_id, o.bsb_address)
        elif action == 'set':
            o.pending_web_requests.append(('ack%d'%disp_id, rq))
            o.send_set(disp_id, value, o.bsb_address, validate=True)
        else:
            raise ValueError('unsupported action')
    
    def on_bsb_telegrams(o, telegrams):
        for telegram in telegrams:
            if telegram.dst==o.bsb_address and telegram.packettype in ['ret', 'ack']:
                key = '%s%d'%(telegram.packettype, telegram.field.disp_id)
                # Answer ALL pending requests for that field.
                for rq in o.pending_web_requests:
                    if rq[0] == key:
                        rq[1].put(telegram)
                # and remove from pending-list
                o.pending_web_requests = [rq for rq in o.pending_web_requests if rq[0] != key]

    def on_send_error(o, error: Exception, disp_id: int, from_address: int):
        for (key, rq) in o.pending_web_requests:
            if key in ('ret%d'%disp_id, 'ack%d'%disp_id):
                rq.put(error)
        o.pending_web_requests = [rq for rq in o.pending_web_requests if rq[0] not in ('ret%d'%disp_id, 'ack%d'%disp_id)]

        
        
# Ripped from web.httpserver, and somewhat modified.
# LICENSE NOTICE: web.py is Public Domain. So this class is exempt from the GPL claim.
class MyLogMiddleware:
    """WSGI middleware for logging the status."""
    def __init__(self, app):
        self.app = app
        self.template = '{host}: {method} {req} - {status}'
        
    def __call__(self, environ, start_response):
        def xstart_response(status, response_headers, *args):
            out = start_response(status, response_headers, *args)
            self.log(status, environ)
            return out

        return self.app(environ, xstart_response)
             
    def log(self, status, environ):
        outfile = environ.get('wsgi.errors', web.debug)
        req = environ.get('PATH_INFO', '_')
        protocol = environ.get('ACTUAL_SERVER_PROTOCOL', '-')
        method = environ.get('REQUEST_METHOD', '-')
        host = "%s:%s" % (environ.get('REMOTE_ADDR','-'), 
                          environ.get('REMOTE_PORT','-'))
        msg = self.template.format(**locals())
        log().info(msg)
