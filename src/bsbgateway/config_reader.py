import logging
import dataclasses as dc
import configparser as cp
import json
import os
from pathlib import Path
from typing import Any

from cattrs import Converter
from cattrs.cols import is_sequence, list_structure_factory


from .gateway_config import GatewayConfig
from .bsb.bsb_comm import AdapterSettings
from .single_field_logger import LoggerConfig
from .cmd_interface import CmdInterfaceConfig
from .web_interface.config import WebInterfaceConfig
from .bsb2tcp import Bsb2TcpSettings

L = lambda: logging.getLogger(__name__)

@dc.dataclass
class Config:
    """Configuration of BSB Gateway."""
    gateway: GatewayConfig
    """Global gateway configuration: Device name and logging."""
    adapter: AdapterSettings
    """Settings for the serial adapter."""
    bsb2tcp: Bsb2TcpSettings
    """Configuration for the BSB to TCP/IP bridge."""
    web_interface: WebInterfaceConfig
    """Web interface configuration."""
    cmd_interface: CmdInterfaceConfig
    """Command line interface configuration."""
    loggers: LoggerConfig
    """Dataloggers"""

def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))

def load_config(force_path:Path|None) -> tuple[Path|None, Config]:
    """Load configuration from default location, unless a specific path is forced.

    if force_path is given, tries to load config from that path.
    
    Otherwise, first tries to load from bsbgateway.ini in the current working directory,
    then from $XDG_CONFIG_HOME/bsbgateway/bsbgateway.ini (var. usually expands to ~/config),
    then from /etc/bsbgateway/bsbgateway.ini.

    If no config file is found, default configuration is generated.

    Returns:
        Tuple of (Path to used config file, Config object). Path is None if no file was used.
    """
    if force_path is not None:
        config_file = force_path
    else:
        config_paths = [
            Path.cwd() / 'bsbgateway.ini',
            xdg_config_home() / 'bsbgateway/bsbgateway.ini',
            Path('/etc/bsbgateway/bsbgateway.ini'),
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
    
    if config_file is None or not config_file.exists():
        L().info("No config file found, using defaults")
        return config_file, _create_default_config()
    
    L().info(f"Loading config from {config_file}")
    parser = cp.ConfigParser()
    parser.read(config_file)
    
    config = _parse_config(parser)
    return config_file, config


def _create_default_config() -> Config:
    """Create a default configuration."""
    return Config(
        gateway=GatewayConfig(),
        adapter=AdapterSettings(),
        web_interface=WebInterfaceConfig(),
        cmd_interface=CmdInterfaceConfig(),
        loggers=LoggerConfig(),
        bsb2tcp=Bsb2TcpSettings(),
    )


def _parse_config(parser: cp.ConfigParser) -> Config:
    """Parse configuration using cattrs"""
    converter = Converter()
    # Convert strings to appropriate types
    converter.register_structure_hook(int, lambda v, _: int(v))
    converter.register_structure_hook(float, lambda v, _: float(v))
    str2bool = lambda v: v.lower() in ('true', '1', 'yes', 'on') if isinstance(v, str) else v
    converter.register_structure_hook(bool, lambda v, _: str2bool(v))

    @converter.register_structure_hook_factory(is_sequence) 
    def list_from_json_factory(t, converter):
        base = list_structure_factory(t, converter)  # delegates to element hooks

        def hook(value, _t):
            if isinstance(value, str):
                value = value.lower().replace("none", "null")  # allow 'none' as null
                value = json.loads(value)
            return base(value, _t)

        return hook   

    raw:dict[str, dict[str, Any]] = {sec.lower(): dict(parser.items(sec)) for sec in parser.sections()}
    if "adapter" not in raw:
        raise ValueError("Missing required 'adapter' section in config")
    for section in ("loggers", "gateway"):
        # Use defaults if section missing
        raw.setdefault(section, {})
    for section in ("cmd_interface", "web_interface", "bsb2tcp"):
        # Disable if section missing
        raw.setdefault(section, {"enable": "false"})

    # Special-case handling
    if "expect_cts_state" in raw["adapter"]:
        val = raw["adapter"]["expect_cts_state"].lower()
        if val in ("", "null", "none"):
            raw["adapter"]["expect_cts_state"] = None
    cfg = converter.structure(raw, Config)
    return cfg


def save_config(config: Config, path: Path) -> None:
    """Save configuration to a file in INI format.
    
    Writes the Config object to a configuration file in INI format at the specified path.
    Uses dataclass introspection to handle all fields automatically.
    
    Args:
        config: The Config object to save.
        path: The Path where the configuration file should be saved.
    """
    parser = _config_to_configparser(config)
    
    # Write to file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        parser.write(f)
    
    L().info(f"Configuration saved to {path}")

def _config_to_configparser(cfg: Config) -> cp.ConfigParser:
    data = dc.asdict(cfg)  # {'debug': True, 'db': {'host': 'localhost', 'port': 5432}}

    parser = cp.ConfigParser()

    # Nested dicts become sections
    for section, v in data.items():
        parser[section] = {ik: str(iv) for ik, iv in v.items()}

    return parser
