# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import logging
import datetime
from queue import Empty

from flask import render_template, request, jsonify
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound

from bsbgateway.bsb.model import BsbCommand, BsbDatatype
from bsbgateway.web_interface import Web2Bsb
from .utils import format_readonly_value, format_range, parse_value

log = lambda: logging.getLogger(__name__)


def register_routes(
    app,
    web2bsb: "Web2Bsb",
    dash_fields: list[BsbCommand] | None = None,
    dash_breaks: list[int] | None = None,
):
    """Register all Flask routes with the app."""
    dash_breaks = dash_breaks or []
    dash_fields = dash_fields or []

    def get_field_value(field_id):
        """Get a field's value from the heater."""
        queue = web2bsb.get(field_id)
        try:
            telegram = queue.get(timeout=4.0)
        except Empty:
            log().error(f"timeout while requesting field {field_id}")
            raise InternalServerError("Data query from heater timed out.")

        if telegram is None:
            raise NotFound()
        if isinstance(telegram, Exception):
            log().error(f"error while requesting field {field_id}: {telegram}")
            raise InternalServerError(str(telegram))

        return {
            "disp_id": telegram.field.disp_id,
            "disp_name": telegram.field.disp_name,
            "timestamp": telegram.timestamp,
            "data": telegram.data,
        }

    @app.route("/")
    def index():
        """Dashboard and group listing."""
        # Create body HTML
        index_html = render_template(
            "index.html",
            fields=dash_fields,
            groups=web2bsb.groups,
            dash_breaks=dash_breaks,
        )

        return render_template(
            "base.html",
            title="",
            body=index_html,
        )

    @app.route("/group-<string:group_id>")
    def group(group_id):
        """Display a group of fields."""
        group_obj = web2bsb.groups.get(group_id, None)
        if group_obj is None:
            raise NotFound()

        group_html = render_template(
            "group.html",
            group=group_obj,
        )
        return render_template(
            "base.html",
            title=f"#{group_obj.name}",
            body=group_html,
        )

    @app.route("/field-<int:field_id>", methods=["GET"])
    def field_get(field_id):
        """Handle GET requests for a field."""
        field = web2bsb.fields[field_id]

        # Return full page with field
        body = render_template(
            "field.html",
            field=field,
        )
        return render_template(
            "base.html",
            title=f"{field.disp_id} {field.disp_name}",
            body=body,
        )

    @app.route("/field-<int:field_id>.fragment", methods=["GET"])
    def field_get_fragment(field_id):
        field = web2bsb.fields[field_id]
        return render_template("field.html", field=field)

    @app.route("/field-<int:field_id>.widget", methods=["GET"])
    def field_get_widget(field_id):
        field = web2bsb.fields[field_id]
        value_info = get_field_value(field_id)
        print("value: ",value_info)
        return render_template(
            "field_widget.html",
            field=field,
            value=value_info["data"],
            format_readonly_value=format_readonly_value,
            format_range=format_range,
        )

    @app.route("/field-<int:field_id>.dashwidget", methods=["GET"])
    def field_get_dashwidget(field_id):
        field = web2bsb.fields[field_id]
        return render_template("field_dashwidget.html", field=field)

    @app.route("/field-<int:field_id>.value", methods=["GET"])
    def field_get_value(field_id):
        value_info = get_field_value(field_id)
        return jsonify(value_info)

    @app.route("/field-<int:field_id>", methods=["POST"])
    def field_post(field_id):
        """Handle POST requests to set a field value."""
        field = web2bsb.fields[field_id]

        # Raises BadRequest on failure.
        # Note that value might be valid but still illegal (e.g. out of range).
        value = parse_value(field, request.form)
        log().info(f"set field {field_id} to value {value!r}")

        try:
            queue = web2bsb.set(field_id, value)
            telegram = queue.get(timeout=4.0)
        except Empty:
            log().error(f"timeout while setting field {field_id}")
            raise InternalServerError("Data request to heater timed out.")

        if telegram is None:
            raise NotFound()
        if isinstance(telegram, Exception):
            log().error(f"error while setting field {field_id}: {telegram}")
            raise InternalServerError(str(telegram))

        return "OK"
