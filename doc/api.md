# BsbGateway - API & Advanced usage

This guide covers programmatic access to BsbGateway:

* HTTP-JSON API,
* adding own functionality, e.g. custom dataloggers or interfaces,
* adding own I/O driver,
* using data model.


## HTTP API for Remote Access

The web interface exposes a JSON API. Here are the key endpoints:

### Get Field Value

**Request:** `GET /field-<id>.value`

**Example:**
```bash
curl http://localhost:8082/field-8007.value
```

**Response:**
```json
{
  "disp_id": 8007,
  "disp_name": "Status Solar",
  "timestamp": 1706470234,
  "value": [1, "On"],
}
```

### Set Field Value

**Request:** `POST /field-<id>` with form data. Allowed / expected parameters are:

* `value` for "normal" fields
* (Subset of) `year`, `month`, `day`, `hour`, `minute`, `second` for date/time-y fields
* `set_null=1` to reset a nullable field to NULL value.

**Examples:**
```bash
# Set numeric value
curl -X POST http://localhost:8082/field-8510 -d "value=22.5"

# Set time value
curl -X POST http://localhost:8082/field-1610 -d "hour=14&minute=30"

# Set choice/enum value (use index)
curl -X POST http://localhost:8082/field-8007 -d "value=0"

# Clear a nullable field
curl -X POST http://localhost:8082/field-8510 -d "set_null=1"
```

**Response:** JSON with updated value or error message

### Error Handling

When a request fails, you get HTTP status 400 or 500 with a JSON error:

```json
{
  "error": "Validation failed: value out of range (min: 5, max: 30)"
}
```

### Timeout Behavior

- Each field query sends a GET telegram to the heating system
- If no response is received within 2-5 seconds, the request returns 500 error
- No automatic retries are performed by the web interface
- The browser timeout typically is 30 seconds per HTTP request

### Listing groups / fields / metadata

Not yet implemented.


## Extending and reusing BsbGateway

BsbGateway consists of well-separated modules, that interact via events and method calls.

* Components receive messages by normal method calls, and send messages via `@event` methods.
* Usually they require one or more internal threads, which are started by `<component>.start_thread()`.

### Adding custom functionality

You can add own module. Here's a barebone example how this would look like:

```python
import threading

from .bsb.bsb_telegram import BsbTelegram
from .hub.event import event

class ExampleModule:
    bsb_address = 29
    disp_id = 8700

    def __init__(self):
        self.stop_event = threading.Event()

    # outbound interface
    @event
    def send_get(disp_id: int, from_address: int):
        """Request a GET command to be sent to the bus"""
        # Events don't have a body

    # inbound interface
    def on_bsb_telegram(self, telegrams: list[BsbTelegram]):
        """Handle incoming BSB telegrams"""
        for telegram in telegrams:
            print(f"Received telegram: {telegram}")

    def start_thread(self):
        """Starts the example module in a separate thread."""
        self.stop_event.clear()
        thread = threading.Thread(target=self.run)
        # Not strictly required if you call stop() as you should.
        thread.daemon = True 
        thread.start()

    def run(self):
        # Send Get requests every second
        while not self.stop_event.wait(1.0):
            self.send_get(self.disp_id, self.bsb_address)

    def stop(self):
        self.stop_event.set()
```

Take note of:

* `send_get` event: this can be called like a function within the module's code (e.g. last line of `run()`) and requests the central hub to do something.
* `on_bsb_telegram` method: this is intended to be called by the central hub. Other than that it's just a plain method.
* `start_thread()`, `stop()` to manage the independent thread.

Save e.g. to `example_module.py`.

To make BsbGateway use this module, you have to extend [bsb_gateway.py](../src/bsbgateway/bsb_gateway.py):

1. Instanciate your module and add it as member to `BsbGateway`.
2. In `setup_modules()`, connect the relevant events - just copy what you see here.
3. Also in `setup_modules()`, call the `ExampleModule.start_thread()` method
4. In the `quit()` method, call `ExampleModule.stop()` for clean shutdown.

The added lines might look like this:

```python
from my_module import MyModule

# ...
class BsbGateway:
    def __init__(o, ...):
        # ...
        o.my_module = MyModule()
    #...
    def setup_modules(o):
        # ...
        # _marshal will queue all incoming events on the main thread.
        o.my_module.send_get += _marshal(o.on_send_get)
        o.my_module.start_thread()
    #...
    def on_bsb_telegrams(o, telegrams):
        #...
        o.my_module.on_bsb_telegrams(telegrams)
    #... 
    def quit(o, ...):
        #...
        o.my_module.stop()
```

As you see, the only "magic" thing happening here is the event processing. Don't
worry about it and just copy what's already there.

### Custom I/O Adapter

You might want to use a custom driver to talk to the bus. An Adapter is just another kind of module. It must implement the following interface:

```python
class MyAdapter:
    @event
    def rx_bytes(data: bytes):
        """To be emitted when data is received from the bus."""

    def tx_bytes(self, ,data:bytes):
        """Called to send to the bus"""
        # ...
    def start_thread(self):
        ...

    def stop(self):
        ...
```

To make it known and used, extend the `get_adapter()` function in [adapter.py](../src/bsbgateway/hub/adapter.py).

```python
def get_adapter(settings: AdapterSettings) -> SerialSource|TcpAdapter|MyAdapter:
    #...
    elif settings.adapter_type == 'my_adapter':
        return MyAdapter()
    #...
```

### Using device information: BsbModel

The json device information is read into dataclasses. Please see [model.py](../src/bsbgateway/bsb/model.py) for definitions and documentation.

Loading happens in `bsb_gateway:run()` (model variable).


```python
from bsbgateway.bsb.model import BsbModel, BsbCommand, BsbDatatype

model = BsbModel.parse_file("devices/broetje_isr_plus.json")

# Get a field by display ID
field = model.fields[8700]
print(f"Description: {field.description}")
print(f"Type: {field.type}")
print(f"Writable: {field.rw}")

# List all fields in a group
print()
print("List category 1600")
category = model.categories["1600"]
for field in category.commands:
    print(f"{field.disp_id}: {field.description}")
```
