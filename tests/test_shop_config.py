import json
import tempfile
import unittest
from pathlib import Path

from vapor_board.config import ShopConfig, load_shop_config, save_shop_config


class ShopConfigTests(unittest.TestCase):
    def test_safe_defaults(self):
        config = ShopConfig()
        self.assertFalse(config.transmissions_enabled)
        self.assertFalse(config.mqtt_enabled)
        self.assertTrue(config.customer_access_requires_approval)
        self.assertEqual(config.minimum_customer_age, 21)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shop.json"
            original = ShopConfig(shop_name="Example Shop", accent_color="#112233")
            save_shop_config(original, path)
            self.assertEqual(load_shop_config(path), original)

    def test_missing_file_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_shop_config(Path(directory) / "missing.json"), ShopConfig())

    def test_invalid_settings_rejected(self):
        for kwargs in ({"shop_name": ""}, {"accent_color": "blue"},
                       {"minimum_customer_age": 18}, {"transmissions_enabled": "false"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ShopConfig(**kwargs)

    def test_unknown_settings_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shop.json"
            path.write_text(json.dumps({"radio_password": "secret"}))
            with self.assertRaises(ValueError):
                load_shop_config(path)

    def test_appearance_and_text_size(self):
        config = ShopConfig()
        self.assertEqual((config.appearance, config.text_size), ("system", "standard"))
        ShopConfig(appearance="dark", text_size="larger")
        for kwargs in ({"appearance": "purple"}, {"text_size": "huge"}, {"appearance": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ShopConfig(**kwargs)

    def test_branding_and_alert_defaults(self):
        config = ShopConfig()
        self.assertEqual((config.kiosk_logo, config.kiosk_tagline, config.kiosk_text_size, config.message_alerts), ("", "", "large", True))

    def test_branding_and_alert_settings_are_checked(self):
        for kwargs in ({"kiosk_logo": 5}, {"kiosk_logo": "x" * 501}, {"kiosk_tagline": "x" * 121}, {"kiosk_text_size": "huge"}, {"message_alerts": "yes"}):
            with self.subTest(kwargs):
                with self.assertRaises(ValueError):
                    ShopConfig(**kwargs)

    def test_update_check_is_off_by_default_and_profile_is_limited(self):
        self.assertFalse(ShopConfig().check_for_updates)
        for kwargs in ({"check_for_updates": 1}, {"shop_hours": "x" * 161}, {"shop_contact": 5}):
            with self.subTest(kwargs):
                with self.assertRaises(ValueError):
                    ShopConfig(**kwargs)

    def test_older_settings_files_still_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shop.json"
            path.write_text(json.dumps({"shop_name": "Old Shop", "operator_name": "Pat", "accent_color": "#112233"}))
            config = load_shop_config(path)
            self.assertEqual((config.shop_name, config.appearance, config.text_size), ("Old Shop", "system", "standard"))


if __name__ == "__main__":
    unittest.main()
