"""Shadow adapter package exposing config loading helpers for tests."""

from .core.config import ConfigError, load_provider_config, ProviderConfig

__all__ = ["ConfigError", "ProviderConfig", "load_provider_config"]
