import logging
import datetime
import sys

from .manage import cli_menu
from . import bsb_gateway
from . import config_reader

log = lambda: logging.getLogger(__name__)


def main():
    """Main entry point for the BsbGateway application."""
    path, config = config_reader.load_config()
    logging.basicConfig(level=config.gateway.loglevel)
    log().info('BsbGateway (c) J. Loehnert 2013-2026, starting @%s' % 
               datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log().info("Using config file: %s", path)
    if sys.argv[1:] and sys.argv[1] == "manage":
        cli_menu(config, path)
    else:
        bsb_gateway.run(config)


if __name__ == '__main__':
    main()