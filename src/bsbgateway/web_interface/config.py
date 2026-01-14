# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import dataclasses as dc


@dc.dataclass
class WebInterfaceConfig:
    """Configuration for the web interface."""

    enable: bool = True
    """Enable web interface yes/no"""

    port: int = 8082
    """Port to bind the web interface to."""

    bsb_address: int = 25
    """Bus address to use for web interface requests."""

    web_dashboard: list[list[int | None]] = dc.field(default_factory=lambda: [])
    """Fields to display as "dashboard" on the index page.
    List of lists, making up a table.
    You can set entries to None to leave gaps.
    """
