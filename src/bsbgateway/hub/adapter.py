# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

from .adapter_settings import AdapterSettings
from .serial_source import SerialSource
from .tcp_adapter import TcpAdapter

def get_adapter(settings: AdapterSettings) -> SerialSource|TcpAdapter:
    """instanciate an Adapter according to the given settings."""
    # Simulation is running as a special SerialSource for historical reasons.
    if settings.adapter_type in ('serial', 'sim'):
        return SerialSource.from_adapter_settings(settings)
    elif settings.adapter_type == 'tcp':
        return TcpAdapter.from_adapter_settings(settings)
    else:
        raise ValueError(f"Unknown adapter type: {settings.adapter_type}")