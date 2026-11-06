"""Minimal MQTT v3.1.1 client for Home Assistant battery auto-discovery."""

from __future__ import annotations

import json
import re
import shlex
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logging import get_logger
from .battery import extract_bluetooth_mac

logger = get_logger(__name__)

DEFAULT_MQTT_ENV_FILE = Path("/etc/default/bluetooth_2_usb_mqtt")
DEFAULT_MQTT_PORT = 1883
MQTT_SOCKET_TIMEOUT_SEC = 3.0


@dataclass(frozen=True, slots=True)
class MqttConfig:
    host: str
    port: int = DEFAULT_MQTT_PORT
    username: str = ""
    password: str = ""
    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "bluetooth_2_usb"


def _parse_env_value(raw_value: str) -> str:
    stripped = raw_value.strip()
    if not stripped:
        return ""
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError:
        return stripped
    return parts[0] if len(parts) == 1 else stripped


def load_mqtt_config(env_file: Path = DEFAULT_MQTT_ENV_FILE) -> MqttConfig | None:
    """Load optional MQTT settings from /etc/default/bluetooth_2_usb_mqtt."""
    if not env_file.is_file():
        return None
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, raw_value = raw_line.split("=", 1)
        values[key.strip()] = _parse_env_value(raw_value)

    host = values.get("B2U_MQTT_HOST", "").strip()
    if not host:
        return None
    try:
        port = int(values.get("B2U_MQTT_PORT", str(DEFAULT_MQTT_PORT)))
    except ValueError:
        port = DEFAULT_MQTT_PORT

    return MqttConfig(
        host=host,
        port=port,
        username=values.get("B2U_MQTT_USERNAME", ""),
        password=values.get("B2U_MQTT_PASSWORD", ""),
        discovery_prefix=values.get("B2U_MQTT_DISCOVERY_PREFIX", "homeassistant") or "homeassistant",
        topic_prefix=values.get("B2U_MQTT_TOPIC_PREFIX", "bluetooth_2_usb") or "bluetooth_2_usb",
    )


def _encode_length(length: int) -> bytes:
    out = bytearray()
    while True:
        encoded = length % 128
        length //= 128
        if length > 0:
            encoded |= 0x80
        out.append(encoded)
        if length == 0:
            break
    return bytes(out)


def _encode_str(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(2, "big") + raw


def _build_connect_packet(client_id: str, username: str, password: str) -> bytes:
    flags = 0x02
    payload = bytearray(_encode_str(client_id))
    if username:
        flags |= 0x80
        payload.extend(_encode_str(username))
        if password:
            flags |= 0x40
            payload.extend(_encode_str(password))
    var_header = _encode_str("MQTT") + bytes([0x04, flags, 0x00, 0x3C])
    body = var_header + bytes(payload)
    return b"\x10" + _encode_length(len(body)) + body


def _build_publish_packet(topic: str, payload: str, *, retain: bool = True) -> bytes:
    header_byte = 0x31 if retain else 0x30
    body = _encode_str(topic) + payload.encode("utf-8")
    return bytes([header_byte]) + _encode_length(len(body)) + body


def publish_mqtt_messages(config: MqttConfig, messages: list[tuple[str, str]]) -> bool:
    """Connect to the MQTT broker and publish (topic, payload) pairs with retain=True."""
    if not messages:
        return True
    try:
        with socket.create_connection((config.host, config.port), timeout=MQTT_SOCKET_TIMEOUT_SEC) as sock:
            sock.sendall(_build_connect_packet("bluetooth_2_usb", config.username, config.password))
            connack = sock.recv(4)
            if len(connack) < 4 or connack[0] != 0x20 or connack[3] != 0x00:
                logger.warning("MQTT broker %s:%s rejected connection (connack=%r)", config.host, config.port, connack)
                return False
            for topic, payload in messages:
                sock.sendall(_build_publish_packet(topic, payload, retain=True))
            sock.sendall(b"\xe0\x00")
        return True
    except OSError as exc:
        logger.debug("MQTT publish to %s:%s failed: %s", config.host, config.port, exc)
        return False


def _device_slug(device: Any) -> str:
    mac = extract_bluetooth_mac(device)
    if mac:
        return mac.replace(":", "")
    raw_name = getattr(device, "name", "") or getattr(device, "path", "device")
    slug = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    return slug or "device"


def build_ha_battery_messages(config: MqttConfig, device: Any, battery_percent: int) -> list[tuple[str, str]]:
    """Build Home Assistant MQTT Discovery config and state messages for a device's battery."""
    slug = _device_slug(device)
    device_name = (getattr(device, "name", "") or "").strip() or f"Bluetooth Device {slug}"
    node_id = f"bluetooth_2_usb_{slug}"
    state_topic = f"{config.topic_prefix}/{slug}/battery"
    discovery_topic = f"{config.discovery_prefix}/sensor/{node_id}/battery/config"
    discovery_payload = json.dumps(
        {
            "name": "Battery",
            "unique_id": f"{node_id}_battery",
            "state_topic": state_topic,
            "unit_of_measurement": "%",
            "device_class": "battery",
            "state_class": "measurement",
            "device": {"identifiers": [node_id], "name": device_name, "manufacturer": "Bluetooth-2-USB"},
        },
        separators=(",", ":"),
    )
    return [(discovery_topic, discovery_payload), (state_topic, str(battery_percent))]


def publish_device_battery(device: Any, battery_percent: int, *, env_file: Path = DEFAULT_MQTT_ENV_FILE) -> bool:
    """Publish a device's battery level to Home Assistant via MQTT if configured."""
    config = load_mqtt_config(env_file)
    if config is None:
        return False
    messages = build_ha_battery_messages(config, device, battery_percent)
    return publish_mqtt_messages(config, messages)
