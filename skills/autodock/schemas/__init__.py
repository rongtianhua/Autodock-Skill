"""SnakeMake workflow configuration schemas."""
from .docking_config import DockingConfig, validate_config

__all__ = ["DockingConfig", "validate_config"]
