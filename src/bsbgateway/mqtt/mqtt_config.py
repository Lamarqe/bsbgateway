import dataclasses as dc


@dc.dataclass
class MqttConfig:
    """Configuration for Home Assistant MQTT interface.

    Please set at least mqtt_host, mqtt_user and mqtt_password.
    """

    enable: bool = False
    """Enable MQTT interface."""
    fields: list[int] = dc.field(default_factory=list)
    """List of disp_ids to be published via MQTT."""
    poll_intervall: int = 2
    """Interval in s between updates of readonly fields. Multiple of 1 second.

    Readonly and writable fields are polled with different intervals, because
    the former are usually sensor values that can change anytime, while the
    latter are typically setpoints that change infrequently.

    Fields will be polled in round-robin fashion. I.e. if you have 6 fields and
    a poll interval of 2 seconds, each field will be updated every 12 seconds.
    """
    poll_intervall_writable: int = 300
    """Interval in seconds between updates of writable fields.
    
    Writable fields are typically setpoints that change infrequently. Thus the poll interval can and should be longer.

    NB. If fields are changed by user action, we will probably also see the
    "set" message and update the MQTT value immediately, regardless of this
    interval.
    """
    hass_id: str = "heating"
    """Home Assistant device ID."""
    mqtt_host: str = ""
    """MQTT broker host."""
    mqtt_port: int = 1883
    """MQTT broker port. Usually the default 1883."""
    mqtt_user: str = ""
    """MQTT username."""
    mqtt_password: str = ""
    """MQTT password."""
    bsb_address: int = 29
    """Address for queries sent to BSB devices."""
