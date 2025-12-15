# bsbgateway
Read and write data on a [BSB](doc/protocol.md) (Boiler System Bus).

Functionalities offered:

 * [Commandline interface](doc/cmdline.md). Enter `help` to get list of commands, `help <cmd>` for documentation of a specific command.
 * [Web interface](doc/web.md) at port :8081 (e.g. http://localhost:8081)
 * [Logging of fields](doc/logging.md) with preset interval. The logs are written in ASCII `.trace` files and can be loaded with `trace/load_trace.py` into `numpy` arrays.


## Hardware

You need hardware to interface with the bus. In priniple, a serial port and a level converter / galvanic decoupler is required.
The circuit that I use is drawn [here](doc/hardware.md), but not recommended for rebuilding.

The serial port driver evaluates the `CTS` (clear-to-send) pin of the RS232 in order to check if the bus is free. Depending on your circuit, you may want to change the settings (esp. invert/no invert) in ([bsb_comm.py](bsbgateway/bsb/bsb_comm.py)), around line 60.


## Some words of caution

The list of fields in here (in [broetje_isr_plus.py](bsbgateway/bsb/broetje_isr_plus.py) ) was gathered mostly from bus-sniffing my own heating system. In the meantime, the guys at the [BSB_LAN](https://github.com/fredlcore/BSB-LAN) project did an incredible job of gathering this information for hundreds of devices.

As it turns out, there is no real standardization of the device data. **The parameters available differ in meaning, telegram structure and scope significantly**, sometimes even within the same controller model, but across different firmware versions. The big issue here is that one telegram structure might work on a different heater without an issue, but the conversion factor might be 2 instead of 1, 5 instead of 10 or vice versa or something completely different. While this will not immediately damage your heating system, **it can make it run very inefficiently or strain the components**, and you might not even notice where the problem comes from, because, on the web-interface, it still says that the minimum break betweek burner starts is 10 minutes, whereas your heater actually thinks of the same value as 1 minute, for example. ([More information](https://github.com/fredlcore/BSB-LAN/discussions/482))

So, please check all fields of interest against *your* device. Compare what bsbgateway tells you with what you see on the local control panel. That applies especially if you intend to set data and not only monitor it. Use the [dump](https://github.com/loehnertj/bsbgateway/blob/master/doc/cmdline.md#sniffing-the-bus) command for sniffing, and if necessary, edit the field list in the python file. (At some point in the future, it might be possible to put the parameter list in a JSON file - currently this is in eternally-half-finished-state.)


## Installation

Dependencies are web.py and pySerial.
To install them, use `pip install -r requirements.txt`

Clone or download the project.

Edit `config.py` to your liking.

Run using `sh bsbgateway.sh`.

For continuous operation, it is (currently) recommendable to run in a `screen` environment like so:

`screen -dmS bsbgateway '/bin/sh /path/to/bsbgateway.sh'`

## Hacking; State of the project

I'm aware that this project looks a bit sad nowadays. I made this in 2012 more or less for my own purpose, and mostly implemented what I needed for myself. However I will respond to issues & PR's; and if there are requests of large-enough public interest, I might have a look at them. ;-)
