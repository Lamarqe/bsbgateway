# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

from .adapter_settings import AdapterSettings
from .serial_source import SerialSource

def get_adapter(settings: AdapterSettings) -> SerialSource:
    """instanciate an Adapter according to the given settings."""
    return SerialSource.from_adapter_settings(settings)