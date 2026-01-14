# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (c) 2026 Johannes Löhnert <loehnert.kde@gmx.de>

import logging
import getpass
from pathlib import Path
import tempfile
import subprocess
import sys

from . import bsb_gateway


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

def cli_menu(config):
    running = True
    while running:
        print("""*** BsbGateway management menu ***

    r) Run BsbGateway within terminal
    i) Install system service (requires root)
    u) Uninstall system service (requires root)

    q) Quit""")
        choice = input(">").lower()
        match choice:
            case "q":
                running = False
            case "r":
                running = False
                bsb_gateway.run(config)
            case "i":
                install_service()
            case "u":
                uninstall_service()