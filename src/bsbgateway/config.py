import dataclasses as dc


from .gateway_config import GatewayConfig
from .bsb.bsb_comm import AdapterSettings
from .single_field_logger import LoggerConfig
from .cmd_interface import CmdInterfaceConfig
from .web_interface.config import WebInterfaceConfig
from .bsb2tcp import Bsb2TcpSettings

@dc.dataclass
class Config:
    """Configuration of BSB Gateway."""
    gateway: GatewayConfig = dc.field(default_factory=GatewayConfig)
    """Global gateway configuration: Device name and logging."""
    adapter: AdapterSettings = dc.field(default_factory=AdapterSettings)
    """Settings for the serial adapter."""
    bsb2tcp: Bsb2TcpSettings = dc.field(default_factory=Bsb2TcpSettings)
    """Configuration for the BSB to TCP/IP bridge."""
    web_interface: WebInterfaceConfig = dc.field(default_factory=WebInterfaceConfig)
    """Web interface configuration."""
    cmd_interface: CmdInterfaceConfig = dc.field(default_factory=CmdInterfaceConfig)
    """Command line interface configuration."""
    loggers: LoggerConfig = dc.field(default_factory=LoggerConfig)
    """Dataloggers"""

    @classmethod
    def default(cls):
        """Default configuration"""
        return cls()