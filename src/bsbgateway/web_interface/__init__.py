# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import logging
from pathlib import Path
from queue import Queue

from flask import Flask
from werkzeug.serving import make_server

from bsbgateway.bsb.model import BsbCategory, BsbCommand, BsbModel
from bsbgateway.bsb.bsb_telegram import BsbTelegram
from bsbgateway.hub.event_sources import EventSource
from bsbgateway.hub.event import event
from .config import WebInterfaceConfig

log = lambda: logging.getLogger(__name__)


class WebInterface(EventSource):
    """Web interface for BSB Gateway using Flask."""
    # Leave me time to shut down properly
    _as_daemon = False

    def __init__(self, config: WebInterfaceConfig, device:BsbModel):
        self.device = device
        self.web2bsb = Web2Bsb(device, bsb_address=config.bsb_address)
        self.port = config.port

        # Build dashboard fields and break points
        dash_fields = []
        dash_breaks = []
        n = 0
        for row in config.web_dashboard or []:
            if not row:
                continue
            dash_breaks.append(n)
            for disp_id in row:
                n += 1
                dash_fields.append(
                    device.fields.get(disp_id, None) if disp_id else None
                )

        self.dash_fields = dash_fields
        self.dash_breaks = dash_breaks[1:]
        self.stoppable = False
        self.server = None
        self.app = None

    def run(self):
        """Start the Flask web server."""
        template_dir = Path(__file__).parent
        self.app = Flask(__name__, template_folder=str(template_dir))

        # Register blueprints/routes
        from . import routes

        routes.register_routes(
            self.app, self.web2bsb, self.dash_fields, self.dash_breaks
        )

        log().info("Web interface listening on http://0.0.0.0:%d/", self.port)

        # Start server
        self.server = make_server("0.0.0.0", self.port, self.app, threaded=True)
        self.server.serve_forever()

    def stop(self):
        """Stop the Flask web server."""
        if self.server:
            self.server.shutdown()
            self.server = None


class Web2Bsb:
    """Bridge between web interface and BSB backend."""

    def __init__(self, device:BsbModel, bsb_address=25):
        self.device:BsbModel = device
        self.bsb_address = bsb_address
        self.pending_web_requests = []

    @property
    def fields(self) -> dict[int, "BsbCommand"]:
        return self.device.fields

    @property
    def groups(self) -> dict[str, BsbCategory]:
        return self.device.categories

    @event
    def send_get(disp_id: int, from_address: int):  # type:ignore
        """Request to get a field value from BSB device.

        Args:
            disp_id: display id of the field to get.
            from_address: address to use on the BSB bus.
        """

    @event
    def send_set(disp_id: int, value, from_address: int, validate: bool):  # type:ignore
        """Request to set a field value on BSB device.

        Args:
            disp_id: display id of the field to set.
            value: value to set.
            from_address: address to use on the BSB bus.
            validate: whether to validate the value.
        """

    def get(self, disp_id: int):
        """Request a field value from BSB device."""
        rq = Queue()
        self._bsb_send(rq, "get", disp_id)
        return rq

    def set(self, disp_id: int, value):
        """Request to set a field value on BSB device."""
        rq = Queue()
        self._bsb_send(rq, "set", disp_id, value)
        return rq

    def _bsb_send(self, rq, action, disp_id, value=None):
        """Internal method to send BSB requests."""
        if action == "get":
            self.pending_web_requests.append(("ret%d" % disp_id, rq))
            self.send_get(disp_id, self.bsb_address)
        elif action == "set":
            self.pending_web_requests.append(("ack%d" % disp_id, rq))
            self.send_set(disp_id, value, self.bsb_address, validate=True)
        else:
            raise ValueError("unsupported action")

    def on_bsb_telegrams(self, telegrams:list[BsbTelegram]):
        """Handle incoming BSB telegrams."""
        for telegram in telegrams:
            if telegram.dst == self.bsb_address and telegram.packettype in [
                "ret",
                "ack",
            ]:
                key = "%s%d" % (telegram.packettype, telegram.field.disp_id)
                # Answer ALL pending requests for that field.
                for rq in self.pending_web_requests:
                    if rq[0] == key:
                        rq[1].put(telegram)
                # Remove from pending list
                self.pending_web_requests = [
                    rq for rq in self.pending_web_requests if rq[0] != key
                ]

    def on_send_error(self, error: Exception, disp_id: int, from_address: int):
        """Handle BSB send errors."""
        for key, rq in self.pending_web_requests:
            if key in ("ret%d" % disp_id, "ack%d" % disp_id):
                rq.put(error)
        self.pending_web_requests = [
            rq
            for rq in self.pending_web_requests
            if rq[0] not in ("ret%d" % disp_id, "ack%d" % disp_id)
        ]
