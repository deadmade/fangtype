"""Configuration settings for the fangtype language server."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fangtype.utils.json_value import JSONValue

logger = logging.getLogger(__name__)
VALID_DIAGNOSTIC_SEVERITIES = {"error", "warning", "information", "hint"}
VALID_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}


@dataclass
class Settings:
    """Settings for the fangtype server, updatable via workspace/didChangeConfiguration."""

    # Whether to run mypy validation for diagnostics
    mypy_enabled: bool = True

    # Whether to run mypy validation for inference results (e.g. inlay hints)
    mypy_inference_validation_enabled: bool = False

    # Minimum severity for diagnostics (error, warning, information, hint)
    diagnostic_severity: str = "information"

    # Whether to run the expensive project-wide cross-file contract search (jedi get_references).
    cross_file_contracts_enabled: bool = True

    # Re-applied to the root logger on change (no restart); matches server.py's bootstrap default.
    log_level: str = "warning"

    # Pushed once at initialize to keep Jedi/mypy project-aware from a managed venv; None = own env.
    project_interpreter: str | None = None
    project_root: str | None = None

    # Token bumped on inference-affecting changes; part of DocumentCache key. Not in init/repr/eq.
    _generation: int = field(default=0, init=False, repr=False, compare=False)

    @property
    def generation(self) -> int:
        """Current inference-settings generation (see ``_generation``)."""
        return self._generation

    def update_launch_context(self, opts: dict[str, JSONValue]) -> None:
        """Set project interpreter/root from ``initializationOptions``; empty/non-string clears."""
        interpreter = opts.get("projectInterpreter")
        self.project_interpreter = (
            interpreter if isinstance(interpreter, str) and interpreter else None
        )
        root = opts.get("projectRoot")
        self.project_root = root if isinstance(root, str) and root else None
        logger.debug(
            "Launch context: project_interpreter=%r project_root=%r",
            self.project_interpreter,
            self.project_root,
        )

    def update(self, config: dict[str, JSONValue]) -> None:
        """Update settings from a config dict (usually from the client)."""
        # Depending on the client, the section can be returned directly or nested.
        plugin_config: JSONValue = config
        nested = config.get("fangtype")
        if isinstance(nested, dict):
            plugin_config = nested

        if not isinstance(plugin_config, dict):
            logger.warning("Ignoring non-dictionary settings payload")
            return

        # Only cross_file_contracts_enabled changes raw inference, so only its flip busts the cache.
        contracts_before = self.cross_file_contracts_enabled

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

            if normalized_key == "log_level":
                if isinstance(value, str) and value.lower() in VALID_LOG_LEVELS:
                    self.log_level = value.lower()
                    logging.getLogger().setLevel(self.log_level.upper())
                    logger.debug(f"Setting log_level = {self.log_level}")
                else:
                    logger.warning(f"Ignoring invalid logLevel value: {value!r}")
                continue

            if normalized_key in {
                "mypy_enabled",
                "mypy_inference_validation_enabled",
                "cross_file_contracts_enabled",
            }:
                if isinstance(value, bool):
                    setattr(self, normalized_key, value)
                    logger.debug(f"Setting {normalized_key} = {value}")
                else:
                    logger.warning(f"Ignoring non-boolean value for {key!r}")

        if self.cross_file_contracts_enabled != contracts_before:
            self._generation += 1

        logger.info("Server settings updated")

    def _to_snake_case(self, key: str) -> str:
        """Convert camelCase/PascalCase keys to snake_case."""
        return "".join(["_" + c.lower() if c.isupper() else c for c in key]).lstrip("_")
