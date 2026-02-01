import dataclasses as dc
import itertools as it
import logging
from typing import Any, Callable

from ha_mqtt_discoverable import Settings, DeviceInfo
from ha_mqtt_discoverable.sensors import (
    BinarySensor,
    BinarySensorInfo,
    Sensor,
    SensorInfo,
    Number,
    NumberInfo,
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
                return HFI("binary", "", lambda val: "ON" if val else "OFF")
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
                return HFI("enum", "", lambda val: options.get(val, f"Unknown ({val})"))
        case BsbDatatype.String:
            return HFI("", "")
        case BsbDatatype.TimeProgram:
            convert = lambda value: ", ".join(
                f"{se.on.strftime('%H:%M')}-{se.off.strftime('%H:%M')}" for se in value
            )
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
        return vals_types[name]
    # default: generic sensor, value converted by str()
    return HFI("", "")


class MyBinarySensor(BinarySensor):
    """Binary sensor with value conversion."""

    def __init__(
        self, mqtt, entity: BinarySensorInfo, value_converter: Callable[[Any], Any] | None
    ):
        super().__init__(Settings(mqtt=mqtt, entity=entity))
        self._value_converter = value_converter

    def set_state(self, value: Any):
        """Set the state of the binary sensor."""
        if self._value_converter:
            super().update_state(self._value_converter(value))
        else:
            super().update_state(value)


class MySensor(Sensor):
    """Sensor with value conversion."""

    def __init__(self, mqtt, entity: SensorInfo, value_converter: Callable[[Any], Any] | None):
        super().__init__(Settings(mqtt=mqtt, entity=entity))
        self._value_converter = value_converter

    def set_state(self, state: Any, last_reset: Any = None):
        """Set the state of the sensor."""
        if self._value_converter:
            super().set_state(self._value_converter(state), last_reset=last_reset)
        else:
            super().set_state(state, last_reset=last_reset)


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

    # inbound interface
    def on_bsb_telegrams(self, telegrams: list[BsbTelegram]):
        """Handle incoming BSB telegrams"""
        for telegram in telegrams:
            # Don't filter by destination. We don't care who asked.
            if telegram.packettype in ("ret", "set", "inf"):
                if telegram.field.disp_id in self.entities:
                    self.entities[telegram.field.disp_id].set_state(telegram.data)

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
            entity = self._field2entity(field, device_info, mqtt_settings)
            self.entities[field.disp_id] = entity

    def _field2entity(self, field: BsbCommand, device_info: DeviceInfo, mqtt):
        """Helper to create an MQTT entity info from a BSB field."""
        hass_field_info = _get_info(field)
        if BsbCommandFlags.Readonly not in field.flags:
            # TODO: Create writable entity if sensibly possible.
            pass
        if hass_field_info.device_class == "binary":
            # Binary Sensor
            info = BinarySensorInfo(
                device=device_info,
                unique_id=f"{self.config.hass_id}_{field.disp_id}",
                name=field.disp_name,
                device_class=hass_field_info.device_class,
            )
            L().debug("Binary Sensor info: %s", info)
            return MyBinarySensor(mqtt=mqtt, entity=info, value_converter=hass_field_info.converter)
        # Sensor
        info = SensorInfo(
            device=device_info,
            unique_id=f"{self.config.hass_id}_{field.disp_id}",
            name=field.disp_name,
            # "measurement": This is a current-time reading, not an aggregate or forecast.
            state_class="measurement",
            device_class=hass_field_info.device_class or None,
            # Only certain units are allowed. So don't rely on the field metadata, prefer the infered unit.
            unit_of_measurement=hass_field_info.unit or field.unit,
        )
        L().debug("Sensor info: %s", info)
        return MySensor(mqtt=mqtt, entity=info, value_converter=hass_field_info.converter)

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

    def stop(self):
        self._mqtt_ready = False
        self.shutdown_device()

    def shutdown_device(self):
        """Cleans up the MQTT device."""
        # Entities are stopped when they are deleted.
        self.entities = {}
        self._client.loop_stop()
