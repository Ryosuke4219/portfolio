"""Shadow adapter package exposing config loading helpers for tests."""
from .core.config import ConfigError, ProviderConfig, load_provider_config

__all__ = ["ConfigError", "ProviderConfig", "load_provider_config"]
