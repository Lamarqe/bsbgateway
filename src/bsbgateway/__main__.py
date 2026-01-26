import logging
import datetime
from pathlib import Path
import sys

from .manage import cli_menu
from . import bsb_gateway
from . import config_reader

log = lambda: logging.getLogger(__name__)


def main():
    """Main entry point for the BsbGateway application."""
    force_path = None
    manage = False
    argv = sys.argv[1:]
    while argv:
        word = argv.pop(0)
        if word == "--config":
            if argv:
                force_path = Path(argv.pop(0))
            else:
                log().error("Missing argument for --config")
                sys.exit(1)
        elif word == "manage":
            manage = True
    path, config = config_reader.load_config(force_path)
    logging.basicConfig(level=config.gateway.loglevel)
    log().info('BsbGateway (c) J. Loehnert 2013-2026, starting @%s' % 
               datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log().info("Using config file: %s", path)
    if manage:
        cli_menu(config, path)
    else:
        bsb_gateway.run(config)


if __name__ == '__main__':
    main()