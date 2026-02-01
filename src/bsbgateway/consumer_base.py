import logging

from .bsb.bsb_telegram import BsbTelegram
from .hub.event import event

L = lambda: logging.getLogger(__name__)

class ConsumerBase:
    """Abstract Base class for consumer modules.

    A consumer module connects to the BsbGateway event bus, and can
    send get/set requests, and receives bsb_telegrams and send_error events.

    Provides stubs for the events (send_get, send_set) and handlers
    (on_bsb_telegrams, on_send_error).

    Subclasses can ignore any of these methods if not needed.
    """ 

    @event
    def send_get(disp_id: int, from_address: int): #type: ignore
        """Request to get a field value from BSB device."""

    @event
    def send_set(disp_id: int, value, from_address: int, validate: bool): #type: ignore
        """Request to set a field value on BSB device."""

    def on_bsb_telegrams(o, telegrams: list[BsbTelegram]):
        """Handle incoming BSB telegrams"""
        pass

    def on_send_error(o, error: Exception, disp_id: int, from_address: int):
        """Handle send errors"""

    def tick(o):
        """Called once per second by the timer source. 
        
        You can use this to perform actions without having to make an own
        thread."""

    def start_thread(o):
        """Starts the consumer's thread(s), if any."""

    def stop(o):
        """Stops the consumer's thread(s), if any."""