# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import logging
import getpass
from pathlib import Path
import tempfile
import subprocess
import sys

from . import bsb_gateway
from . import config_ui


SERVICE_TEMPLATE = """[Unit]
Description=BSB Gateway service
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User={user}
StandardInput=data
StandardInputText=
ExecStart={script}

[Install]
WantedBy=multi-user.target
"""

SERVICE_FILE = Path("/etc/systemd/system/bsbgateway.service")

SERVICE_NAME = "bsbgateway"

INSTALL_CMD = """
cp {{tmpfile}} {service_file} && \\
systemctl daemon-reload && \\
systemctl enable {service_name} && \\
systemctl start {service_name} && \\
systemctl status {service_name}
""".format(service_name=SERVICE_NAME, service_file=SERVICE_FILE)

UNINSTALL_CMD = """
systemctl stop {service_name}
systemctl disable {service_name}
rm {service_file}
systemctl daemon-reload
""".format(service_name=SERVICE_NAME, service_file=SERVICE_FILE)


L = lambda: logging.getLogger(__name__)

def sudo(*cmd):
    """execute command string with superuser rights"""
    cmdstr = " ".join(cmd)
    L().info(f"sudo {cmdstr}")
    try:
        result = subprocess.run(['pkexec', '--user', 'root', *cmd], 
                      check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        L().warning(f"Sudo failed: {e.stderr}")
        raise RuntimeError()
    else:
        L().info(f"{result.stdout}\n{result.stderr}")

def install_service():
    """Installs the software as systemd service.
    
    The software will run under the current user account and with the current command line.
    """
    L().info(f"Installing {SERVICE_FILE}")
    script = Path(sys.argv[0]).absolute()
    user = getpass.getuser()
    content = SERVICE_TEMPLATE.format(script=script, user=user)
    with tempfile.NamedTemporaryFile("w") as f:
        f.write(content)
        f.flush()
        install_cmd = INSTALL_CMD.format(tmpfile=f.name)
        sudo("sh", "-c", install_cmd)

def uninstall_service():
    """Uninstalls service"""
    sudo("sh", "-c", UNINSTALL_CMD)

def configure(config, config_path:Path|None):
    """Interactive configuration of the BsbGateway config object."""
    new_config, is_changed = config_ui.run(config)
    if is_changed:
        from .config_reader import save_config, xdg_config_home
        if config_path:
            L().info(f"Saving updated configuration to {config_path}")
            save_config(new_config, config_path)
        else:
            config_dir = xdg_config_home() / "bsbgateway"
            config_dir.mkdir(parents=True, exist_ok=True)
            new_config_path = config_dir / "bsbgateway.ini"
            L().info(f"Saving new configuration to {new_config_path}")
            save_config(new_config, new_config_path)
    else:
        L().debug("No changes made to configuration.")
    return new_config


def change_loglevel(level:str):
    """Change loglevel of the root logger."""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        L().warning(f"Invalid log level: {level}")
        return
    logging.getLogger().setLevel(numeric_level)

def cli_menu(config, config_path:Path|None):
    running = True
    while running:
        print("""\n=== BsbGateway management menu ===

  c) Configure BsbGateway
  r) Run BsbGateway within terminal
  i) Install system service (requires root)
  s) restart system service (requires root)
  u) Uninstall system service (requires root)

  x) Exit""")
        choice = input(">").lower()
        match choice:
            case "x":
                running = False
            case "c":
                config = configure(config, config_path)
                change_loglevel(config.gateway.loglevel)
            case "r":
                running = False
                bsb_gateway.run(config)
            case "i":
                install_service()
            case "s":
                sudo("systemctl", "restart", SERVICE_NAME)
            case "u":
                uninstall_service()