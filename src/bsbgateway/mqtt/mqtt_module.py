import dataclasses as dc
import itertools as it
import logging
from typing import Any, Callable

from ha_mqtt_device import Settings, DeviceInfo
from ha_mqtt_device.sensors import (
    BinarySensor,
    BinarySensorInfo,
    Sensor,
    SensorInfo,
    Number,
    NumberInfo,
    Switch,
    SwitchInfo,
    Select,
    SelectInfo,
)
from paho.mqtt.client import Client, MQTTMessage

from bsbgateway.consumer_base import ConsumerBase

from ..bsb.model import BsbCommand, BsbCommandFlags, BsbDatatype, BsbModel, BsbType
from ..bsb.bsb_telegram import BsbTelegram
from ..hub.event import event

from .mqtt_config import MqttConfig

L = lambda: logging.getLogger(__name__)


@dc.dataclass
class HaFieldInfo:
    """Holds Home Assistant entity info for a BSB field."""

    device_class: str
    """Device class i.e. physical meaning of the value.
    
    See https://developers.home-assistant.io/docs/core/entity/sensor/#device-class
    
    Empty string marks the generic device class."""
    unit: str
    """Unit of measurement, e.g. °C, %, etc.

    For each device class, only certain units are allowed.
    """
    converter: Callable[[Any], Any] | None = None
    """Convert the BSB field value to a suitable format for Home Assistant.
    
    If not set, no conversion is done."""
    rw_entity: str = ""
    """Entity class to choose if the field is writable
    
    Empty string if we don't support this type - then the representation is
    read-only even if the field is writable.
    """


def _get_info(field: BsbCommand) -> HaFieldInfo:
    """Return device class and unit for a given BSB field type.

    Uses field datatype, type name to provide sensor type (device_class), unit and if necessary, value converter function.
    """
    HFI = HaFieldInfo
    field_type = field.type
    if field_type is None:
        return HFI("", "")
    # first, try by type
    match field_type.datatype:
        case BsbDatatype.Datetime:
            return HFI("timestamp", "", lambda val: val.isoformat())
        case BsbDatatype.DayMonth:
            return HFI("date", "", lambda val: val.isoformat())
        case BsbDatatype.Time:
            return HFI("", "", lambda val: val.strftime("%H:%M:%S"))
        case BsbDatatype.HourMinutes:
            return HFI("", "", lambda val: val.strftime("%H:%M"))
        case BsbDatatype.Enum:
            if field_type.name in ("ONOFF", "YESNO"):
                # "binary is not actually allowed for a sensor, instead it will become a binary_sensor.
                return HFI("binary", "", lambda val: "ON" if val else "OFF", rw_entity="switch")
            else:
                options = {}
                if field_type.name == "WEEKDAY":
                    options = {
                        7: "Sunday",
                        1: "Monday",
                        2: "Tuesday",
                        3: "Wednesday",
                        4: "Thursday",
                        5: "Friday",
                        6: "Saturday",
                    }
                options.update({key: str(val) for key, val in field.enum.items()})
                return HFI(
                    "enum", "", lambda val: options.get(val, f"Unknown ({val})"), rw_entity="select"
                )
        case BsbDatatype.String:
            # We could set rw_entity="text", however typically strings are read-only status fields.
            return HFI("", "")
        case BsbDatatype.TimeProgram:
            convert = lambda value: ", ".join(
                f"{se.on.strftime('%H:%M')}-{se.off.strftime('%H:%M')}" for se in value
            )
            # TODO: how to make this writable? Could use the text format as in
            # the web interface, but that seems a bit fragile.
            return HFI("", "", convert)
        case BsbDatatype.Bits:
            # val is bytes type
            return HFI("", "", lambda val: val.hex())
    vals_types = {
        "TEMP": HFI("temperature", "°C"),
        "POWER": HFI("power", "kW"),
        "POWER100": HFI("power", "kW"),
        "ENERGY": HFI("energy", "kWh"),
        "PRESSURE": HFI("pressure", "bar"),
        "PRESSURE50": HFI("pressure", "bar"),
        # actually ATM_PRESSURE but our name-mangling logic cuts off the second word.
        "ATM": HFI("pressure", "hPa"),
        "LITERPERMIN": HFI("volume_flow_rate", "L/min"),
        "LPM": HFI("volume_flow_rate", "L/min"),
        "LITERPERHOUR": HFI("volume_flow_rate", "L/h"),
        # ?: per HA list, only A or mA is allowed. Will something bad happen if we use µA?
        "CURRENT": HFI("current", "µA"),
        "CURRENT1000": HFI("current", "µA"),
        "VOLTAGE": HFI("voltage", "V"),
        "SECONDS": HFI("duration", "s"),
        "MINUTES": HFI("duration", "min"),
        "HOURS": HFI("duration", "h"),
        "DAYS": HFI("duration", "d"),
    }
    # For lookup, remove suffix. E.g we have SECONDS, SECONDS_WORD, SECONDS_SHORT etc -> map all to SECONDS
    name, _, _ = field_type.name.partition("_")
    if name in vals_types:
        return dc.replace(vals_types[name], rw_entity="number")
    # default: generic sensor, value converted by str()
    return HFI("", "", rw_entity="number")


class MyEntityBase:
    """Base class for our simplified and unified MQTT entities.

    - simplified: no need to create EntityInfo and Settings separately.
    - unified: Common update_from_bsb() method to set the state from a BSB value;
      common set_from_mqtt() event to forward MQTT command to BSB.
    """

    field: BsbCommand

    @event
    def set_from_mqtt(disp_id: int, value: Any):  # type:ignore
        """Set a value received from MQTT to the BSB bus.

        Payload is the value received from MQTT, already converted to the correct type by the MQTT entity.
        """

    def update_from_bsb(self, value: Any):
        """Set the state of the MQTT entity from a value received from the BSB bus.

        Payload is the value decoded from the BSB telegram, before any conversion for Home Assistant.
        """
        raise NotImplementedError("Must be implemented by subclass.")

    def convert_bsb2mqtt(self, value: Any, /) -> Any:
        """Convert a BSB value to the appropriate type for MQTT payload."""
        # This method will be overridden by the specific entity classes (e.g. switch, number) to convert the value accordingly.
        return value

    def callback(self, client: Client, user_data, msg: MQTTMessage):
        """Callback function to handle MQTT messages for writable entities."""
        try:
            payload = msg.payload.decode("utf-8")
            value = self.convert_mqtt2bsb(payload)
            L().info(f"Set field {self.field.disp_id} to value {value!r} (MQTT payload was {payload!r})")
            self.set_from_mqtt(self.field.disp_id, value)
        except Exception as e:
            L().exception("Error processing MQTT command for field %s: %s", self.field.disp_id, e)

    def convert_mqtt2bsb(self, payload: str) -> Any:
        """Convert the MQTT payload string to the appropriate type for the BSB field."""
        # This method will be overridden by the specific entity classes (e.g. switch, number) to convert the payload accordingly.
        return payload


class MyBinarySensor(BinarySensor, MyEntityBase):
    """Binary sensor with value conversion."""

    def __init__(self, mqtt, device, field: BsbCommand, hass_field_info: HaFieldInfo):
        self.field = field
        entity = BinarySensorInfo(
            device=device,
            unique_id=f"{device.name}_{field.disp_id}",
            name=field.disp_name,
            device_class=hass_field_info.device_class or None,
        )
        super().__init__(Settings(mqtt=mqtt, entity=entity))
        if hass_field_info.converter:
            self.convert_bsb2mqtt = hass_field_info.converter

    def update_from_bsb(self, value: Any):
        """Set the state of the binary sensor."""
        super().update_state(self.convert_bsb2mqtt(value))


class MySensor(Sensor, MyEntityBase):
    """Sensor with value conversion."""

    def __init__(
        self,
        mqtt,
        device,
        field: BsbCommand,
        hass_field_info: HaFieldInfo,
    ):
        self.field = field
        entity = SensorInfo(
            device=device,
            unique_id=f"{device.name}_{field.disp_id}",
            name=field.disp_name,
            # "measurement": This is a current-time reading, not an aggregate or forecast.
            state_class="measurement",
            device_class=hass_field_info.device_class or None,
            # Only certain units are allowed. So don't rely on the field metadata, prefer the infered unit.
            unit_of_measurement=hass_field_info.unit or field.unit,
        )
        super().__init__(Settings(mqtt=mqtt, entity=entity))
        if hass_field_info.converter:
            self.convert_bsb2mqtt = hass_field_info.converter

    def update_from_bsb(self, value: Any):
        """Set the state of the sensor."""
        super().set_state(self.convert_bsb2mqtt(value))


class MyNumber(Number, MyEntityBase):
    """Number entity with value conversion."""

    def __init__(
        self,
        mqtt,
        device,
        field: BsbCommand,
        hass_field_info: HaFieldInfo,
    ):
        self.field = field
        entity = NumberInfo(
            device=device,
            unique_id=f"{device.name}_{field.disp_id}",
            name=field.disp_name,
            unit_of_measurement=hass_field_info.unit or field.unit,
            min=field.min_value or 0.0,
            max=field.max_value or 100.0,
        )
        super().__init__(Settings(mqtt=mqtt, entity=entity), command_callback=self.callback)
        if hass_field_info.converter:
            self.convert_bsb2mqtt = hass_field_info.converter

    def update_from_bsb(self, value: Any):
        """Set the state of the number entity."""
        super().set_value(self.convert_bsb2mqtt(value))

    def convert_mqtt2bsb(self, payload: str) -> Any:
        """Convert the MQTT payload string to a number."""
        # Just let callback() handle any exceptions.
        if "." in payload:
            return float(payload)
        else:
            return int(payload)

class MySelect(Select, MyEntityBase):
    """Select entity with value conversion."""

    def __init__(
        self,
        mqtt,
        device,
        field: BsbCommand,
        hass_field_info: HaFieldInfo,
    ):
        self.field = field
        self._option2num = {str(val).lower(): key for key, val in field.enum.items()}
        entity = SelectInfo(
            device=device,
            unique_id=f"{device.name}_{field.disp_id}",
            name=field.disp_name,
            options=[str(val) for val in field.enum.values()],
        )
        super().__init__(s:=Settings(mqtt=mqtt, entity=entity), command_callback=self.callback)
        if hass_field_info.converter:
            self.convert_bsb2mqtt = hass_field_info.converter

    def update_from_bsb(self, value: Any):
        """Set the state of the select entity."""
        # conversion of numeric value to option string is handled by
        # convert_bsb2mqtt, which is set to the appropriate enum-to-string
        # converter in _get_info().
        # TODO: code smell here!
        super().select_option(self.convert_bsb2mqtt(value))

    def convert_mqtt2bsb(self, payload: str) -> Any:
        """Convert the MQTT payload string to the corresponding enum value."""
        # Just let callback() handle any exceptions.
        if payload.lower() not in self._option2num:
            raise ValueError(f"Invalid option for select entity: {payload}")
        return self._option2num[payload.lower()]

class MySwitch(Switch, MyEntityBase):
    """Switch entity with value conversion."""

    def __init__(
        self,
        mqtt,
        device,
        field: BsbCommand,
        hass_field_info: HaFieldInfo,
    ):
        self.field = field
        entity = SwitchInfo(
            device=device,
            unique_id=f"{device.name}_{field.disp_id}",
            name=field.disp_name,
        )
        super().__init__(Settings(mqtt=mqtt, entity=entity), command_callback=self.callback)
        if hass_field_info.converter:
            self.convert_bsb2mqtt = hass_field_info.converter

    def update_from_bsb(self, value: Any):
        """Set the state of the switch."""
        if self.convert_bsb2mqtt(value):
            super().on()
        else:
            super().off()

    def convert_mqtt2bsb(self, payload: str) -> Any:
        """Convert the MQTT payload string to a boolean."""
        val = payload.strip().upper()
        if val in ("ON", "1", "TRUE"):
            return True
        elif val in ("OFF", "0", "FALSE"):
            return False
        else:
            raise ValueError(f"Invalid payload for switch: {payload}")

def _field2entity(field: BsbCommand, device_info: DeviceInfo, mqtt) -> MyEntityBase:
    """Helper to create an MQTT entity info from a BSB field."""
    hass_field_info = _get_info(field)
    if BsbCommandFlags.Readonly not in field.flags and hass_field_info.rw_entity:
        # Create writable entity
        match hass_field_info.rw_entity:
            case "switch":
                cls = MySwitch
            case "number":
                cls = MyNumber
            case "select":
                cls = MySelect
            case _:
                cls = MySensor
    else:
        if hass_field_info.device_class == "binary":
            cls = MyBinarySensor
        else:
            cls = MySensor
    return cls(mqtt=mqtt, device=device_info, field=field, hass_field_info=hass_field_info)

class MqttModule(ConsumerBase):
    def __init__(self, config: MqttConfig, bsb_model: BsbModel):
        if not config.enable:
            raise ValueError("MQTT module is not enabled in the configuration.")
        if not config.fields:
            raise ValueError("MQTT module has no fields configured to publish.")
        if config.poll_intervall_writable <= config.poll_intervall:
            raise ValueError(
                "MQTT module writable poll intervall must be greater than read-only poll intervall."
            )
        self.config = config
        self.bsb_model = bsb_model
        self.time_since_poll = 0
        self._client = Client(client_id="bsbgateway_mqtt_module")
        self.entities: dict[int, Any] = {}
        """Maps disp_id to MQTT entity."""
        fields = [bsb_model.fields[disp_id] for disp_id in config.fields]
        ro_field_ids = [f.disp_id for f in fields if BsbCommandFlags.Readonly in f.flags]
        rw_field_ids = [f.disp_id for f in fields if BsbCommandFlags.Readonly not in f.flags]
        self.disp_ids_to_poll_ro = it.cycle(ro_field_ids)
        self.disp_ids_to_poll_rw = it.cycle(rw_field_ids)
        self._mqtt_ready = False
        self._initial_poll_count = max(len(ro_field_ids), len(rw_field_ids))
        """Number of initial polls to perform to populate all entities. Initial poll has fixed 1s delay."""
        self._poll_rw_each = max(2, config.poll_intervall_writable // config.poll_intervall)
        """Poll one writable field every _poll_rw_each read-only polls."""
        self._poll_rw_counter = 0
        """Counts read-only polls to determine when to poll writable fields."""

    # outbound interface
    @event
    def send_get(disp_id: int, from_address: int):  # type:ignore
        """Request a GET command to be sent to the bus"""

    @event
    def send_set(disp_id: int, value: Any, from_address: int, validate: bool):  # type:ignore
        """Request a SET command to be sent to the bus."""

    # inbound interface
    def on_bsb_telegrams(self, telegrams: list[BsbTelegram]):
        """Handle incoming BSB telegrams"""
        for telegram in telegrams:
            # Don't filter by destination. We don't care who asked.
            if telegram.packettype in ("ret", "set", "inf"):
                if telegram.field.disp_id in self.entities:
                    self.entities[telegram.field.disp_id].update_from_bsb(telegram.data)

    def start_thread(self):
        """Starts the example module. Threads are created implicitly by MQTT setup."""
        self._client.username = self.config.mqtt_user
        self._client.password = self.config.mqtt_password
        self._client.connect(
            host=self.config.mqtt_host,
            port=self.config.mqtt_port,
        )
        self._client.loop_start()
        self.setup_device()
        self._mqtt_ready = True

    def setup_device(self):
        """Sets up the MQTT device with Home Assistant discovery."""
        mqtt_settings = Settings.MQTT(client=self._client)
        device_info = DeviceInfo(identifiers=self.config.hass_id, name=self.config.hass_id)

        self.entities = {}
        for disp_id in self.config.fields:
            field = self.bsb_model.fields[disp_id]
            entity = _field2entity(field, device_info, mqtt_settings)
            entity.set_from_mqtt += self._on_set_from_mqtt
            self.entities[field.disp_id] = entity

    def tick(self):
        """Poll the BSB bus at regular intervals."""
        if not self._mqtt_ready:
            return
        self.time_since_poll += 1.0
        self._poll_rw_counter += 1
        if self._initial_poll_count > 0:
            # Initial polling phase: poll one field every second to quickly populate all entities.
            self._initial_poll_count -= 1
            in_initial_poll = True
            if self._initial_poll_count == 0:
                L().info("Completed initial polling of all MQTT fields.")
        else:
            in_initial_poll = False

        if self.time_since_poll >= self.config.poll_intervall or in_initial_poll:
            self.time_since_poll = 0.0
            disp_id = next(self.disp_ids_to_poll_ro)
            self.send_get(disp_id, self.config.bsb_address)
            if self._poll_rw_counter >= self._poll_rw_each or in_initial_poll:
                self._poll_rw_counter = 0
                # Send both ro and rw at this time. Rely on builtin throttling
                # to avoid bus overload.
                disp_id = next(self.disp_ids_to_poll_rw)
                self.send_get(disp_id, self.config.bsb_address)

    def _on_set_from_mqtt(self, disp_id: int, value: Any):
        """Handle a set command received from MQTT."""
        self.send_set(disp_id, value, self.config.bsb_address, validate=True)

    def stop(self):
        self._mqtt_ready = False
        self.shutdown_device()

    def shutdown_device(self):
        """Cleans up the MQTT device."""
        # Entities are stopped when they are deleted.
        self.entities = {}
        self._client.loop_stop()
