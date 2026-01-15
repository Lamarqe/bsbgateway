import dataclasses as dc

@dc.dataclass
class GatewayConfig:
    loglevel: str = 'INFO'
    """Logging level for the gateway. One of 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'."""
    device: str = 'broetje_isr_plus'
    """Type of connected device. Currently there is only a (incomplete) driver for Broetje ISR Plus.

    Read "device" = "index of available fields".
    """