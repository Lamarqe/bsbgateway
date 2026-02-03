import dataclasses as dc

@dc.dataclass
class GatewayConfig:
    """Central configuration options."""
    loglevel: str = 'INFO'
    """Logging level for the gateway. One of 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'.
    
    You can also configure individual loggers like this (first part is the root logger):
    'INFO,bsbgateway.mqtt:DEBUG,bsbgateway.bsb:WARNING'
    """
    device: str = 'broetje_isr_plus'
    """Type of connected device. Currently there is only a (incomplete) driver for Broetje ISR Plus.

    Read "device" = "index of available fields".
    """
    locale: str = ''
    """Locale for field names and descriptions, e.g. 'DE' for German, 'EN' for English.
    
    If empty, the system locale is used.
    """