##############################################################################
#
#    Part of BsbGateway
#    Copyright (C) Johannes Loehnert, 2013-2015
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import sys
import time
import logging
log = lambda: logging.getLogger(__name__)

from queue import Queue
from threading import Thread, Event, Lock
from .event import event

__all__ = ['EventSource', 'StdinSource', 'SyncedSecondTimerSource', 'DelaySource']

class EventSource(object):
    '''base class for event sources.
        * run provides the core wait code and must be overriden.
        * use start_thread(putevent_func) to start the source in a new thread.
            * the source will run as daemon if forced shutdown can be tolerated.
            * putevent_func must take name as first and data as second argument
            * name = string
            * data = source specific payload (any python obj).
        * use stop() to make the source stop
            * if source.stoppable=True, it will stop in 1..2 seconds
            * otherwise, it will stop at the next possibility, i.e.
                usually at the next event.
            * You must stop all stoppable sources before exit, since
                their threads will not be killed by themselves.
    '''
    # True if calling stop() will stop the source within 1..2 secs.
    stoppable = False
    _as_daemon = True
    # flag signalling that run() should exit.
    _stopflag = False
    _running = False

    def run(o) -> None:
        '''run the event source. this function does not spawn a new thread.
        The run function should block unless there is an event, in which
        case it calls one of the @events.
        If the source is flagged as stoppable, it must check periodically
        for the _stopflag. If true, run should exit. The check period should
        be 1 second, so that the source stops within 1 .. 2 secs.
        otherwise it should check for the stopflag on the next event.
        '''
        raise NotImplementedError('override me')
        # demo code
        # while not o._stopflag:
        #     time.sleep(1.0)
        #    o.my_event(time.time())

    def start_thread(o, new_thread=True):
        '''starts the source in a new thread and returns the thread.'''
        if not hasattr(o, "name"):
            o.name = o.__class__.__name__
        if new_thread:
            thread = Thread(target=o._run_wrapper, name=o.name)
            thread.daemon = o._as_daemon
            thread.start()
            return thread
        else:
            o._run_wrapper()

    def _run_wrapper(o):
        o._stopflag = False
        o._running = True
        o.run()
        o._running = False
        log().debug('event source %s exited.'%o.name)

    def stop(o):
        '''stop the event source if running.
        note that stopping is only guaranteed if source.stoppable=True.
        Otherwise calling stop() means 'stop somewhen when it fits',
        which usually means stopping at the next event.
        after stop() is called, not putevent_func calls must be issued anymore.
        '''
        if not o._running:
            return
        if not o.stoppable:
            log().debug('event source %s will stop somewhen...'%o.name)
        o._stopflag = True


class StdinSource(EventSource):
    '''waits for data on standard input and returns it.
    always returns a whole line of text.
    The event is fired on each Return key press.
    '''

    def __init__(o):
        o.stoppable = False

    @event
    def line(line:str):
        """A line of text read from standard input."""

    def run(o):
        while True:
            x = sys.stdin.readline()
            if o._stopflag:
                break
            o.line(x)

class SyncedSecondTimerSource(EventSource):
    '''fires every second, exactly at (never before) the second mark.'''
    name = 'timer'
    def __init__(o):
        o.stoppable = True

    @event
    def tick():
        """Timer tick event"""

    def run(o):
        while True:
            t = time.time()
            period = 1.0 - (t%1.0)
            time.sleep(period)
            if o._stopflag:
                break
            o.tick()

def run_test():
    sources = [
        StdinSource('stdin'),
    ]
    for source in sources:
        hub.add_and_start_source(source)

    def myhandler(evtype, data):
        print(evtype, repr(data))
        if evtype=='stdin' and 'q' in data:
            hub.stop()
        if evtype=='timer':
            print(time.time())

    hubthread = hub.start_thread(myhandler)
    hubthread.join()

if __name__=='__main__':
    run_test()
