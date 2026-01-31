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

import time
import logging
from threading import Thread
import queue
import serial
from serial import Serial

from .adapter_settings import AdapterSettings
from .event import event

from ..virtual_serial import VirtualSerial
from ..virtual_device import virtual_device
from .event_sources import EventSource

L = lambda: logging.getLogger(__name__)

class SerialSource(EventSource):
    """ A source for monitoring a COM port. The COM port is 
        opened when the source is started.
        see also EventSource doc.
    
        event data are (timestamp, data) pairs, where data is a binary 
            string representing the received data, and timestamp
            is seconds since epoch as returned by time.time().        

        additionaly, a write() method is offered to write to the port.

        port:
            The COM port to open. Must be recognized by the 
            system.
        
        port_baud: baudrate (int)
        port_stopbits: stopbits (1, 1.5 or 2)
        port_parity: 'none', 'odd' or 'even'
            For stopbits and parity, the constants defined in the serial module can be used, too.
        invert_bytes: invert bytes after reading & before sending (XOR with 0xFF)
        expect_cts_state: None, False or True - if False or True, only send if CTS has that state.
            (only applies to write() function).
        write_retry_time: if blocked by CTS, retry after that time (in seconds). Note that each
            write is delayed AT LEAST that time.
        
    """
    def __init__(o,
        port_num,
        port_baud,
        port_stopbits:float=1,
        port_parity='none',
        invert_bytes = False,
        expect_cts_state = None,
        simulation: bool = False,
        write_retry_time = 0.01,
    ):
        o.stoppable = True
        o.serial_port:Serial|VirtualSerial = None
        o._simulation = simulation
        o._invert_bytes = invert_bytes

        o._expect_cts_state = expect_cts_state
        o._write_retry_time = write_retry_time
        o._write_retry_queue = queue.Queue()

        o._serial_arg = dict( 
            port=port_num,
            baudrate=port_baud,
            stopbits={
                1:serial.STOPBITS_ONE, 
                1.5: serial.STOPBITS_ONE_POINT_FIVE, 
                2: serial.STOPBITS_TWO
            }.get(port_stopbits, port_stopbits),
            parity={
                'none': serial.PARITY_NONE,
                'odd': serial.PARITY_ODD,
                'even': serial.PARITY_EVEN,
            }.get(port_parity, port_parity),
            timeout=1.0,
        )

    @classmethod
    def from_adapter_settings(o, settings:AdapterSettings):
        assert settings.adapter_type in ('serial', 'sim')
        return o(
            port_num=settings.adapter_device,
            # use sane default values for the rest if not set
            port_baud=settings.port_baud,
            port_stopbits=settings.port_stopbits,
            port_parity=settings.port_parity,
            # Most simple RS232 level converters will deliver inverted bytes.
            invert_bytes=settings.invert_bytes,
            expect_cts_state=settings.expect_cts_state,
            write_retry_time=settings.write_retry_time,
            simulation=settings.adapter_type == "sim",
        )

    @event
    def rx_bytes(data:bytes): # type:ignore
        """Data received from the serial port.
        
        Payload is a bytes object.
        """

    def run(o):
        if o._simulation:
            o.serial_port = VirtualSerial(**o._serial_arg, responder=virtual_device)
        else:
            o.serial_port = serial.Serial(**o._serial_arg)
        # activate power supply
        o.serial_port.rts = False
        o.serial_port.dtr = True

        # start delay-write thread if needed
        if o._expect_cts_state is not None:
            t = Thread(target=o._write_delayed)
            t.daemon = True
            t.start()
        while True:
            # Reading 1 byte, followed by whatever is left in the
            # read buffer, as suggested by the developer of 
            # PySerial.
            # read() blocks at most for (timeout)=1 second.
            data = o.serial_port.read(1)
            data += o.serial_port.read(o.serial_port.in_waiting)
            if o._stopflag:
                break

            if len(data) > 0:
                if o._invert_bytes:
                    data = bytearray(data)
                    for i in range(len(data)):
                        data[i] ^= 0xff
                    data = bytes(data)
                o.rx_bytes(data)
        o.serial_port.close()

    def tx_bytes(o, data:bytes):
        if o._invert_bytes:
            data = bytearray(data)
            for i in range(len(data)):
                data[i] ^= 0xff
            data = bytes(data)

        if o._expect_cts_state is not None:
            # put in queue
            o._write_retry_queue.put(data)
        else:
            # clear to send immediately
            o.serial_port.write(data)

    def _write_delayed(o):
        # copy reference to exception, since on destruction, Queue module disappears before I stop.
        empty_exception = queue.Empty
        '''if something appears on the retry queue, wait for the appropriate time, then try to resend.'''
        while not o._stopflag:
            try:
                data = o._write_retry_queue.get(True, 1.0)
            except empty_exception:
                # check stopflag each 1 second, then resume waiting for queue.
                continue
            # initial delay
            time.sleep(o._write_retry_time)
            # wait until clear to send
            cnt = 0
            while cnt < 100 and o.serial_port.cts != o._expect_cts_state:
                time.sleep(o._write_retry_time)
                cnt += 1
                if o._stopflag: return
            if cnt>=100:
                L().error('could not send packet: not clear to send after 100 wait cycles')
                continue
            o.serial_port.write(data)

