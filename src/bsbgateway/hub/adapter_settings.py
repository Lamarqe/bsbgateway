# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import dataclasses as dc
from typing import Literal

@dc.dataclass
class AdapterSettings:
    """Settings for the IO adapter used to connect to the BSB bus.
    
    Hardware settings are ignored when using simulation."""

    adapter_type: Literal["serial", "sim", "tcp"] = "serial"
    """Type of adapter to use: 

    * 'serial' for real serial port
    * 'sim' for simulation
    * 'tcp' to connect to a BsbGateway instance via TCP

    In case of 'tcp', the remote instance must have the Bsb2Tcp module enabled.

    Further required settings depend on the adapter type:

    * sim: only min_wait_s is used.
    * serial: port_baud, port_stopbits, port_parity, adapter_device, invert_bytes, expect_cts_state, write_retry_time, min_wait_s are used.
    * tcp: tcp_host, tcp_port, tcp_token, min_wait_s are used. tcp_token must match the token configured in the remote BsbGateway instance.
    """

    adapter_device: str = "/dev/ttyUSB0"
    """The device name of the serial adapter.

    * '/dev/ttyS0' ... '/dev/ttyS3' are usual devices for real serial ports.
    * '/dev/ttyUSB0' is the usual device for a USB-to-serial converter on Linux.
    """
    port_baud: int = 4800
    """Baudrate - typical value for BSB bus is 4800."""
    port_stopbits: float = 1
    """Stopbits - 1, 1.5 or 2. For BSB bus, use 1."""
    port_parity: str = 'odd'
    """Parity - 'none', 'odd' or 'even'. For BSB bus, use 'odd' if you invert bytes, "even" if not."""
    invert_bytes: bool = True
    """Invert all bits after receive + before send?
    
    If you use a simple BSB-to-UART level converter, you most probably need to
    set this to True.
    """
    expect_cts_state: bool | None = None
    """Only send if CTS has this state (True or False); None to disable.

    Use this if your adapter has a "bus in use" detection wired to CTS pin of
    the RS232 interface.
    """
    write_retry_time: float = 0.005
    """Wait time in seconds if blocked by CTS (see above)."""

    tcp_host: str = ""
    """Hostname or IP address of the remote BsbGateway instance."""
    tcp_port: int = 8580
    """TCP port of the remote BsbGateway instance."""
    tcp_token: str = ""
    """Authentication token for the remote BsbGateway instance, as hex string."""

    min_wait_s: float = 0.1
    """Minimum wait time between subsequent data requests on the bus.

    Used to avoid blocking up the bus when lots of requests come in at once. In case of contention, the oldest requests are dropped.

    Note that the web interface has builtin timeout of 3.0 s. I.e. if you send
    more than (3.0 / min_wait_s) requests at once, data will be lost.
    """