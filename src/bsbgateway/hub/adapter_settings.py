# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import dataclasses as dc

@dc.dataclass
class AdapterSettings:
    """Settings for the IO adapter used to connect to the BSB bus.
    
    Hardware settings are ignored when using simulation."""
    adapter_device: str = "/dev/ttyUSB0"
    """The device name of the serial adapter.

    * '/dev/ttyS0' ... '/dev/ttyS3' are usual devices for real serial ports.
    * '/dev/ttyUSB0' is the usual device for a USB-to-serial converter on Linux.
    * ':sim' opens a simple device simulation (no actual serial port required)
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
    min_wait_s: float = 0.1
    """Minimum wait time between subsequent data requests on the bus.

    Used to avoid blocking up the bus when lots of requests come in at once. In case of contention, the oldest requests are dropped.

    Note that the web interface has builtin timeout of 3.0 s. I.e. if you send
    more than (3.0 / min_wait_s) requests at once, data will be lost.
    """