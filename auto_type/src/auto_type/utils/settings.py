"""Configuration settings for the auto-type language server."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
VALID_DIAGNOSTIC_SEVERITIES = {"error", "warning", "information", "hint"}


@dataclass
class Settings:
    """Settings for the auto-type language server.

    These can be updated dynamically via workspace/didChangeConfiguration.
    """

    # Whether to show inlay hints in the editor
    inlay_hints_enabled: bool = True

    # Whether to show usage-site hints (e.g. for variables used in expressions)
    show_usage_hints: bool = True

    # Whether to prefer modern Python 3.10+ types (list[int] instead of List[int])
    prefer_modern_types: bool = True

    # Whether to run mypy validation for diagnostics
    mypy_enabled: bool = True

    # Whether to run mypy validation for inference results (e.g. inlay hints)
    mypy_inference_validation_enabled: bool = True

    # Minimum severity for diagnostics (error, warning, information, hint)
    diagnostic_severity: str = "information"

    # Whether to skip variables that already have a type annotation when inserting
    skip_annotated: bool = True

    # Custom configuration dictionary (raw)
    _raw_config: dict[str, Any] = field(default_factory=dict, repr=False)

    def update(self, config: dict[str, Any]) -> None:
        """Update settings from a dictionary.

        Args:
            config: New configuration values (usually from the client)
        """
        self._raw_config = config

        # Depending on the client, the section can be returned directly or nested.
        plugin_config = config
        if isinstance(config.get("autoType"), dict):
            plugin_config = config["autoType"]
        elif isinstance(config.get("auto_type"), dict):
            plugin_config = config["auto_type"]

        if not isinstance(plugin_config, dict):
            logger.warning("Ignoring non-dictionary settings payload")
            return

        for key, value in plugin_config.items():
            normalized_key = self._to_snake_case(key)
            if normalized_key == "diagnostic_severity":
                if isinstance(value, str):
                    severity = value.lower()
                    if severity in VALID_DIAGNOSTIC_SEVERITIES:
                        self.diagnostic_severity = severity
                        logger.debug(f"Setting diagnostic_severity = {severity}")
                    else:
                        logger.warning(f"Ignoring invalid diagnosticSeverity value: {value!r}")
                else:
                    logger.warning("Ignoring non-string diagnosticSeverity value")
                continue

            if normalized_key in {
                "inlay_hints_enabled",
                "show_usage_hints",
                "prefer_modern_types",
                "mypy_enabled",
                "mypy_inference_validation_enabled",
                "skip_annotated",
            }:
                if isinstance(value, bool):
                    setattr(self, normalized_key, value)
                    logger.debug(f"Setting {normalized_key} = {value}")
                else:
                    logger.warning(f"Ignoring non-boolean value for {key!r}")

        logger.info("Server settings updated")

    def _to_snake_case(self, key: str) -> str:
        """Convert camelCase/PascalCase keys to snake_case."""
        return "".join(["_" + c.lower() if c.isupper() else c for c in key]).lstrip("_")
