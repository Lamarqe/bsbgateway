# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Johannes Löhnert
import logging
import os
import dataclasses as dc
from quickrpc.network_transports import TcpServerTransport

from bsbgateway.hub.event import event

L= lambda: logging.getLogger(__name__)

@dc.dataclass
class Bsb2TcpSettings:
    """Bridge BSB bus to TCP/IP.
    
    If enabled, a TCP server is started on the specified port.
    Each connected client receives all BSB telegrams, and can send telegrams as well.
    
    The server is protected by a secret token. Clients must send the token when
    they connect. Otherwise they will be ignored.

    Data received from a client is forwarded to the BSB bus, but not the other clients!

    Data received from the bus is forwarded to all authenticated clients.
    """
    enable: bool = False
    """Enable the BSB to TCP/IP bridge."""
    
    port: int = 8580
    """TCP port to listen on."""
    
    token: str = ""
    """Secret token for client authentication. hex string, 32 bytes (64 characters). Spaces are allowed."""

    def get_random_token(o) -> str:
        """get a random token."""
        return os.urandom(32).hex()

    @property
    def token_bytes(o) -> bytes:
        """Get the token as bytes."""
        return bytes.fromhex(o.token)

class Bsb2Tcp:
    """Bridges BSB Bus to a TCP/IP server.
    
    See Bsb2TcpSettings for configuration.
    """
    def __init__(o, settings: Bsb2TcpSettings):
        if not settings.enable:
            raise ValueError("tried to instanciate Bsb2Tcp while disabled in settings")
        o.settings = settings
        if len(settings.token_bytes) != 32:
            raise ValueError("Token must be 32 bytes long")
        o.server = TcpServerTransport(port=settings.port)
        o.server.set_on_received(o._on_tcp_received)
        o.authenticated_clients = set()

    @event
    def rx_bytes(data: bytes):
        """Emitted when data is received from a TCP client.
        """

    def start(o):
        """Start the TCP server."""
        o.server.start()

    def stop(o):
        """Stop the TCP server."""
        o.server.stop()
       
    def tx_bytes(o, data: bytes):
        """Send data to all authenticated TCP clients."""
        o.server.send(data, receivers=list(o.authenticated_clients))

    def _on_tcp_received(o, sender: str, data: bytes) -> bytes:
        """Handle data received from a TCP client. Returns leftover data."""
        # Handle authentication
        connected_clients = {t.name for t in o.server.transports}
        # remove disconnected clients from authenticated list
        o.authenticated_clients.intersection_update(connected_clients)
        if sender not in o.authenticated_clients:
            # expect token
            if data == o.settings.token_bytes:
                o.authenticated_clients.add(sender)
                L().info(f"Client {sender} authenticated with the correct token.")
            else:
                L().warning(f"Client {sender} failed authentication. Disconnecting.")
                o.server.close(sender)
        else:
            # forward to BSB bus
            o.rx_bytes(data)
        # No leftovers ever.
        return b""


    