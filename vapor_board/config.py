"""Local shop configuration; never contains radio credentials or customer records."""

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
APPEARANCES = ("system", "light", "dark")
TEXT_SIZES = ("standard", "large", "larger")
RADIO_TYPES = ("meshtastic", "meshcore")


@dataclass(frozen=True)
class ShopConfig:
    shop_name: str = "Vapor Board"
    # Shared shop mailbox every signed-in staff member reads and sends private messages as.
    operator_name: str = "Operator"
    accent_color: str = "#238C9C"
    notices_enabled: bool = True
    transmissions_enabled: bool = False
    # Receive-only status from a broker on the shop's network. It counts messages; it never publishes.
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_topic: str = "msh/#"
    # meshtastic, or meshcore (listen-only: no replies).
    radio_type: str = "meshtastic"
    customer_access_requires_approval: bool = True
    minimum_customer_age: int = 21
    # Desktop look: "system" follows macOS light/dark; text_size scales every font.
    appearance: str = "system"
    text_size: str = "standard"
    # Return to the sign-in screen after this many idle minutes; 0 never locks.
    auto_lock_minutes: int = 15
    # Customer kiosk: fill the screen, and move to the next board after this many idle seconds (0 = never).
    kiosk_fullscreen: bool = True
    kiosk_rotate_seconds: int = 30
    # Kiosk branding: an image file (PNG or GIF; relative paths are inside ~/.vapor-board), a line under the
    # shop name, and how big notices are for reading from a distance.
    kiosk_logo: str = ""
    kiosk_tagline: str = ""
    kiosk_text_size: str = "large"
    # A sound, Mac notification and on-screen notice when a customer messages the shop.
    message_alerts: bool = True
    # Shown on the kiosk and sent by the radio "info" command; leave empty to hide.
    shop_hours: str = ""
    shop_contact: str = ""
    # Ask GitHub for newer releases at launch. Off by default: the app otherwise never contacts the internet.
    check_for_updates: bool = False
    # Read-only notices for paired customer phones over the shop's Wi-Fi (docs/PHONE_NOTICES.md). Off by default.
    phone_notices_enabled: bool = False
    phone_notices_port: int = 8765
    # Address put in pairing codes; blank uses this Mac's current local address. Reserve it in the router.
    phone_notices_address: str = ""

    def __post_init__(self):
        if not isinstance(self.shop_name, str) or not (1 <= len(self.shop_name.strip()) <= 80):
            raise ValueError("shop_name must contain 1–80 characters")
        if not isinstance(self.operator_name, str) or not (1 <= len(self.operator_name.strip()) <= 80):
            raise ValueError("operator_name must contain 1–80 characters")
        if not isinstance(self.accent_color, str) or not _HEX.fullmatch(self.accent_color):
            raise ValueError("accent_color must be a six-digit hex color")
        for key in ("notices_enabled", "transmissions_enabled", "mqtt_enabled", "customer_access_requires_approval", "kiosk_fullscreen", "message_alerts", "check_for_updates", "phone_notices_enabled"):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f"{key} must be a boolean")
        if type(self.minimum_customer_age) is not int or self.minimum_customer_age < 21:
            raise ValueError("minimum_customer_age must be at least 21")
        if self.appearance not in APPEARANCES:
            raise ValueError(f"appearance must be one of: {', '.join(APPEARANCES)}")
        if type(self.auto_lock_minutes) is not int or not 0 <= self.auto_lock_minutes <= 240:
            raise ValueError("auto_lock_minutes must be a whole number from 0 to 240")
        if type(self.kiosk_rotate_seconds) is not int or not (self.kiosk_rotate_seconds == 0 or 5 <= self.kiosk_rotate_seconds <= 600):
            raise ValueError("kiosk_rotate_seconds must be 0 or from 5 to 600")
        if self.text_size not in TEXT_SIZES:
            raise ValueError(f"text_size must be one of: {', '.join(TEXT_SIZES)}")

        if not isinstance(self.kiosk_logo, str) or len(self.kiosk_logo) > 500:
            raise ValueError("kiosk_logo must be a file path of at most 500 characters")
        if not isinstance(self.kiosk_tagline, str) or len(self.kiosk_tagline) > 120:
            raise ValueError("kiosk_tagline must be at most 120 characters")
        for key in ("shop_hours", "shop_contact"):
            if not isinstance(getattr(self, key), str) or len(getattr(self, key)) > 160:
                raise ValueError(f"{key} must be at most 160 characters")
        if not isinstance(self.mqtt_host, str) or len(self.mqtt_host) > 200 or any(c.isspace() for c in self.mqtt_host):
            raise ValueError("mqtt_host must be a host name or address")
        if type(self.mqtt_port) is not int or not 1 <= self.mqtt_port <= 65535:
            raise ValueError("mqtt_port must be between 1 and 65535")
        if not isinstance(self.mqtt_topic, str) or not 1 <= len(self.mqtt_topic) <= 200 or any(c.isspace() for c in self.mqtt_topic):
            raise ValueError("mqtt_topic must be 1–200 characters without spaces")
        if type(self.phone_notices_port) is not int or not 1024 <= self.phone_notices_port <= 65535:
            raise ValueError("phone_notices_port must be between 1024 and 65535")
        if not isinstance(self.phone_notices_address, str) or len(self.phone_notices_address) > 200 \
                or any(c.isspace() or c in "/?#&@" for c in self.phone_notices_address):
            raise ValueError("phone_notices_address must be a host name or address")
        if self.radio_type not in RADIO_TYPES:
            raise ValueError(f"radio_type must be one of: {', '.join(RADIO_TYPES)}")
        if self.kiosk_text_size not in TEXT_SIZES:
            raise ValueError(f"kiosk_text_size must be one of: {', '.join(TEXT_SIZES)}")

    def to_dict(self):
        return asdict(self)


def load_shop_config(path):
    """Load strict JSON settings; missing files use safe defaults."""
    path = Path(path)
    if not path.exists():
        return ShopConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("shop config must be a JSON object")
    allowed = set(ShopConfig.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"unknown shop settings: {', '.join(sorted(unknown))}")
    return ShopConfig(**data)


def save_shop_config(config, path):
    """Save settings without copying radio secrets or customer information."""
    if not isinstance(config, ShopConfig):
        raise TypeError("config must be ShopConfig")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
