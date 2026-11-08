"""Vapor Board application foundation."""

from .config import ShopConfig, load_shop_config

__version__ = "1.0.0rc3"
VERSION_LABEL = "1.0.0 RC 2"

__all__ = ["ShopConfig", "load_shop_config", "__version__", "VERSION_LABEL"]
