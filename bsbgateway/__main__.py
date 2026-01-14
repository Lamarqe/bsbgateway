import logging
import datetime
from . import bsb_gateway
from . import config_reader

log = lambda: logging.getLogger(__name__)

path, config = config_reader.load_config()
logging.basicConfig(level=config.gateway.loglevel)
log().info('BsbGateway (c) J. Loehnert 2013-2026, starting @%s'%datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
log().info("Using config file: %s", path)
bsb_gateway.run(config)