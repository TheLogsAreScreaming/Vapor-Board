"""Local shop configuration; never contains radio credentials or customer records."""

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
APPEARANCES = ("system", "light", "dark")
TEXT_SIZES = ("standard", "large", "larger")


@dataclass(frozen=True)
class ShopConfig:
    shop_name: str = "Vapor Board"
    # Shared shop mailbox every signed-in staff member reads and sends private messages as.
    operator_name: str = "Operator"
    accent_color: str = "#238C9C"
    notices_enabled: bool = True
    transmissions_enabled: bool = False
    mqtt_enabled: bool = False
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

    def __post_init__(self):
        if not isinstance(self.shop_name, str) or not (1 <= len(self.shop_name.strip()) <= 80):
            raise ValueError("shop_name must contain 1–80 characters")
        if not isinstance(self.operator_name, str) or not (1 <= len(self.operator_name.strip()) <= 80):
            raise ValueError("operator_name must contain 1–80 characters")
        if not isinstance(self.accent_color, str) or not _HEX.fullmatch(self.accent_color):
            raise ValueError("accent_color must be a six-digit hex color")
        for key in ("notices_enabled", "transmissions_enabled", "mqtt_enabled", "customer_access_requires_approval", "kiosk_fullscreen", "message_alerts"):
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
