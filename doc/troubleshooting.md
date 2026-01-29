# BsbGateway - Troubleshooting Guide

## Connection Issues

### "Could not open port"

**Error message:** `serial.serialutil.SerialException: [Errno 2] could not open port /dev/ttyUSB0: [Errno 2] No such file or directory: '/dev/ttyUSB0'` 

**Solutions:**
- Verify the serial port name in your config (`Adapter Device`). Common names are: `/dev/ttyUSB0`, `/dev/ttyACM0`, `/dev/ttyS0`
- Check that your user has permission to access the port:
  - Linux: Add user to `dialout` group: `sudo usermod -a -G dialout $USER` (requires logout/login)
  - Use `ls -la /dev/ttyUSB*` to verify permissions
- Try a different USB port or cable

### "Not clear to send" or not receiving any responses from bus

**Symptoms:** Cannot read data; error message `could not send packet: not clear to send after 100 wait cycles`

**Potential causes:**
- CTS pin not connected or the "Expect CTS state" setting is wrong
- The adapter circuit is not functioning

**Solutions:**
1. Check `Adapter` settings in your config:
   - Try setting "Expect CTS state" to `None`
   - Try toggling "Invert bytes" (for most circuits, this should be ON)
   - Save and restart
2. Use `dump on` in the command interface to monitor all bus traffic. If nothing appears, the circuit isn't receiving.

---

## Web Interface Issues

### "Connection refused" or can't access web interface

**Symptoms:** Browser shows "Unable to connect" or timeout when trying to reach `http://localhost:8082`.

**Solutions:**
- Verify the gateway is running: look for "Web interface listening on" in console output
- Check output / log for the message `Address already in use: Port 8082 is in use by another program. Either identify and stop that program, or start the server with a different port.` - indicates that port is blocked. In particular, the port might remain blocked on unclean shutdown. In this case, it should become free after 30...60 seconds.
- Check the port number in config (`Web Interface / Port`) - default is `8082`
- If accessing from a different machine, use the actual IP address instead of `localhost`

### Web interface shows fields but values don't load

**Symptoms:** Field list loads, but clicking "Load" or "Load all" shows no values.

**Potential causes:**
- JavaScript is disabled in your browser
- The gateway has a communication problem with the heating system
- Browser console shows errors

**Solutions:**
1. **Enable JavaScript** - this is required. Check browser settings.
2. Open browser console (F12) and check for errors:
   - View the "Network" tab and try to load a field value again
   - Look for network errors or timeout messages
   - Common error: "Connection timeout" → indicates bus communication failure
3. Try the command interface instead to verify basic communication works:
   - Run `bsbgateway` and try `get 8700` to fetch a simple field
   - If this fails, the issue is with bus communication, not the web interface

### "Load all" is very slow or times out

**Symptoms:** Clicking "Load all" takes a long time or fails to complete.

**Explanation:** The web interface deliberately adds delays (0.5s per field) to avoid overwhelming the bus. With many fields, this can take a while.

**Solutions:**
- This is normal behavior. Wait longer or load specific fields instead.
- Reduce the number of fields or split into smaller categories in the device definition file.

---

## Command Interface Issues

### Dump filter syntax errors

**Symptoms:** `dump` command returns an error like "invalid syntax" or "unexpected variable".

**Solutions:**
- Remember: Use `=` (not `==`) for comparisons in dump expressions
- Type names don't need quotes: use `type=ack` not `type="ack"`
- Variables available: `src`, `dst`, `field`, `fieldhex`, `type`
- Examples that work:
  ```
  dump field=8007          # All telegrams for field 8007
  dump type=ret            # Only return (response) telegrams
  dump src=0               # Only from the base device (source address 0)
  dump dst=0 or src=0      # To or from address 0
  dump field=8510 and type=set  # Only SET commands for field 8510
  ```

### `get` or `set` command errors, hangs or times out

**Symptoms:** Command appears to hang and doesn't return within a few seconds.

**Causes:**
- Interface not working (see above)
- Heater did not understand message (this is all reverse-engineered...)

**Solutions:**
1. Verify the field ID: `list` command to see available fields
2. Try `dump on` to see if any bus traffic is visible
3. Set Gateway / Loglevel to DEBUG, then try to set the same field using LCD control panel, and compare binary message bytes. Open an issue if you think there's a bug.


### "Field not writable" or validation errors

**Symptoms:** `set` command fails with "field is read-only" or "value out of range".

**Solutions:**
- Use `info <field>` to check if the field is writable, and what the allowed value range is
- For choice fields, use the numeric index (0, 1, 2...), not the text
- To send a forbidden value, append `!` to bypass validation. **Use at your own risk.**
  ```
  set 8510 25.5!
  ```

---

## Logging Issues

### Can't load trace file with `load_trace.py`

**Symptoms:** Error like "file not found" or "invalid format".

**Solutions:**
- Verify the trace file exists: `ls -la /path/to/traces/`
- Make sure you're using the correct file name (field ID + `.trace`)
- Check file permissions: `cat 8510.trace` should show content
- Ensure Python has `numpy` installed: `python -c "import numpy; print(numpy.__version__)"`

---

## Configuration Issues

### Changes to config don't take effect

**Symptoms:** You edit `bsbgateway.ini` but the change doesn't apply.

**Solution:**
- Make sure you edit the right file. Upon start, there is an INFO message giving
the `.ini` file which is used.
- Do not forget to restart the Gateway.
- If running as a service: `sudo systemctl restart bsbgateway.service`
- If running in terminal: press Ctrl+C and start again

### Cannot find device file

**Error message:** `FileNotFoundError: 'asdf.json' not found.`

**Solutions:**
1. Verify the device file path in config (`Gateway / Device`)
   - You should specify just the name without `.json` extension
   - Examples: `my_device`, `broetje_isr_plus` (not `my_device.json`)
2. Check that the file exists:
   - in the working directory (`<device>.json`), or
   - in the user config directory (`~/.config/bsbgateway/<device>.json`), or
   - in the system config directory (`/etc/bsbgateway/<device>.json`).

### Invalid device file

**Error message:** `json.decoder.JSONDecodeError: ...`.

**Solution:**
- The device file must contain valid JSON syntax. Fix the error as indicated by the message.

### Service won't start

**Symptoms:** `systemctl status bsbgateway.service` shows failed or error.

**Solutions:**
1. Check the service log: `journalctl -u bsbgateway.service -n 50`
2. Common issues:
   - Config file not found (check config file path)
   - Venv path broken (if you moved the installation)
   - Serial port access denied (user doesn't have permission)
   - Device file missing
3. Try running manually to see the actual error: `/path/to/bsbgateway/bsbgateway`

---

## Getting Help

If you're stuck, shoot me an issue on [Github](https://github.com/loehnertj/bsbgateway/issues). Please include any information that might be helpful.
