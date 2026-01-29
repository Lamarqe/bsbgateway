# BsbGateway - TCP bridging

BsbGateway can be set up for TCP bridging, i.e. to pass on packets between the bus and TCP clients. Bytes will be forwarded both ways exactly as received.

Each connected TCP client receives all BSB telegrams, and can send telegrams as well.

Data received from a client is forwarded to the BSB bus, but not the other clients.

Data received from the bus is forwarded to all authenticated clients.

The server is protected by a 32-byte token. Clients must send the token as first packet when they connect. A client sending anything else before the token will be disconnected immediately. I know that this is not the most secure protocol ever. **Don't expose the server on the Interwebs.**

### Activating TCP Forwarder

On the machine connected to the actual BSB hardware, enable the `Bsb2Tcp` module in the configuration:

```ini
[bsb2tcp]
enable = True
port = 8580
token = DEADBEEF05060708091011121314151617181920212223242526272829303132
```

When using the interactive configuration (`bsbgateway manage`), there's a menu entry to generate a random token.

This exposes the serial connection as a TCP server on port 8580.

### Setting up TCP Adapter

To use the TCP interface in BsbGateway on another machine, setup the adapter as follows:

```ini
[adapter]
adapter_type = tcp
tcp_host = 192.168.1.100
tcp_port = 8580
; This must be the exact same token that the Forwarder uses
tcp_token = DEADBEEF05060708091011121314151617181920212223242526272829303132
```

You can also connect with any other TCP client, as long as it sends the right token upon connection. All following RX and TX data is raw binary bus traffic.
