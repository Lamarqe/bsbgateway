# MQTT Interface (Home Assistant)

This module publishes BSB fields to Home Assistant via MQTT discovery using the bundled `ha_mqtt_device` library. Once MQTT is configured, entities appear automatically in Home Assistant without manual YAML configuration.

Read-only fields are exposed as sensors, while writable fields are represented as slider / switch / select control as appropriate.

Only explicitly-elected fields are exposed, so that the number of autocreated Home Assistant entities stays manageable.

## Home Assistant MQTT setup in short

If you have no MQTT broker configured yet, this is the first thing to do. The steps are:

1. Install or provide an MQTT broker (e.g. Mosquitto).
2. Add the MQTT integration in Home Assistant.
3. Create MQTT credentials and use them in this project.

For all details, please refer to the official docs.

- Home Assistant MQTT integration: https://www.home-assistant.io/integrations/mqtt/
- MQTT broker setup (Mosquitto): https://www.home-assistant.io/docs/mqtt/broker/
- MQTT discovery (used by this module): https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery

## BSB Gateway MQTT interface setup

The MQTT interface is disabled by default. Enable and configure the MQTT
interface in your bsbgateway configuration file
(bsbgateway.ini) under the section `[mqtt_interface]`. This can be done using
the interactive configuration (`bsbgateway manage` command).

Minimal example:

```ini
[mqtt_interface]
enable = true
fields = [8700, 8701, 8743]
mqtt_host = 192.168.1.10
mqtt_port = 1883
mqtt_user = ha
mqtt_password = secret
```

### Configuration options

- `enable` (bool): Turn the MQTT interface on/off.
- `fields` (list[int]): List of BSB `disp_id`s to publish. E.g. `[8700, 8701]`.
- `poll_intervall` (int): Poll interval for read-only fields (seconds). Default `2`.
- `poll_intervall_writable` (int): Poll interval for writable fields (seconds). Default `300`. Must be **greater** than `poll_intervall`.
- `hass_id` (str): Home Assistant device identifier and name. Default `heating`.
- `mqtt_host` (str): Broker host.
- `mqtt_port` (int): Broker port, default `1883`.
- `mqtt_user` / `mqtt_password` (str): Broker credentials.
- `bsb_address` (int): BSB bus address used for reads/writes. Default `29`.

### What happens after enabling

- On startup, the module connects to the broker and publishes MQTT discovery config for each selected field.
- Each field becomes a Home Assistant entity under the device named by `hass_id`.
- Read-only and writable fields are polled separately. Writable fields are polled less often.
- If a writable entity is changed in Home Assistant (e.g. switch/number/select), the module sends a `SET` command to the BSB bus.

Fields are polled in round-robin fashion. E.g. if you set the poll intervall to
2s and `fields` contains three readonly fields, each individual value is updated each 6s. Values are only published when they actually changed.

Additionally, if field value changes are seen on the bus for other reasons (web
interface, control panel), they will be published in MQTT as well. Thus,
settings changes will typically appear immediately even if
`poll_intervall_writable` is set to a long time.

### Entity mapping

The entity type is inferred from the BSB field datatype:

- Enum `ONOFF`/`YESNO` → `switch` (writable) or `binary_sensor` (read-only)
- Other enums → `select`
- Numeric values (e.g. temperatures, pressure, energy) → `sensor` or `number`.
  In case of a writable (`number`) entity, it is strongly advised to set the value
  limits in the device JSON file.
- Strings, dates, times, time programs → `sensor` (read-only).

If a field is marked read-only in the BSB model, it is exposed as a read-only entity even if the datatype would otherwise allow writes.
