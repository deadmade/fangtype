"""Settings parsing plus initializationOptions and didChangeConfiguration push (no config pull)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fangtype.utils.settings import Settings
from lsprotocol import types

if TYPE_CHECKING:
    from fangtype.server import FangtypeServer


class TestSettingsUpdate:
    """Tests for Settings.update()."""

    def test_updates_from_vscode_section_payload(self) -> None:
        """CamelCase keys from VSCode should map to snake_case fields."""
        settings = Settings()

        settings.update(
            {
                "mypyEnabled": False,
                "diagnosticSeverity": "warning",
            }
        )

        assert settings.mypy_enabled is False
        assert settings.diagnostic_severity == "warning"

    def test_updates_from_nested_autotype_payload(self) -> None:
        """Nested fangtype payloads should also be supported."""
        settings = Settings()

        settings.update({"fangtype": {"mypyEnabled": False}})

        assert settings.mypy_enabled is False

    def test_ignores_invalid_value_types(self) -> None:
        """Invalid value types should not overwrite existing settings."""
        settings = Settings()

        settings.update(
            {
                "mypyEnabled": "false",
                "diagnosticSeverity": 123,
            }
        )

        assert settings.mypy_enabled is True
        assert settings.diagnostic_severity == "information"

    def test_ignores_invalid_diagnostic_severity(self) -> None:
        """Invalid diagnostic severity should keep the previous value."""
        settings = Settings()

        settings.update({"diagnosticSeverity": "critical"})

        assert settings.diagnostic_severity == "information"

    def test_log_level_stores_and_reapplies(self) -> None:
        """logLevel is stored and re-applied to the root logger without a restart."""

        root = logging.getLogger()
        previous = root.level
        try:
            settings = Settings()
            settings.update({"logLevel": "debug"})
            assert settings.log_level == "debug"
            assert root.level == logging.DEBUG

            settings.update({"logLevel": "bogus"})
            assert settings.log_level == "debug"
            assert root.level == logging.DEBUG
        finally:
            root.setLevel(previous)


class TestSettingsDefaults:
    """Defaults must match the VSCode client (package.json / common/settings.ts)."""

    def test_update_omitting_key_leaves_the_other_defaults(self) -> None:
        """A client payload that omits a key must leave that key at its default."""
        settings = Settings()

        settings.update({"mypyEnabled": False})

        assert settings.mypy_enabled is False
        assert settings.cross_file_contracts_enabled is True


class TestSettingsGeneration:
    """The inference-settings generation counter used by the DocumentCache key."""

    def test_starts_at_zero_and_is_excluded_from_equality(self) -> None:
        assert Settings().generation == 0
        # _generation is compare=False, so two default Settings stay equal.
        assert Settings() == Settings()

    def test_bumps_when_cross_file_contracts_flips(self) -> None:
        settings = Settings(cross_file_contracts_enabled=True)
        settings.update({"crossFileContractsEnabled": False})
        assert settings.generation == 1

    def test_does_not_bump_when_contracts_unchanged(self) -> None:
        settings = Settings(cross_file_contracts_enabled=True)
        # A no-op for contracts, plus an unrelated inference-irrelevant change.
        settings.update({"crossFileContractsEnabled": True, "diagnosticSeverity": "warning"})
        assert settings.generation == 0

    def test_does_not_bump_on_unrelated_settings(self) -> None:
        settings = Settings()
        settings.update({"mypyEnabled": False, "diagnosticSeverity": "error"})
        assert settings.generation == 0


class TestLaunchContext:
    """Launch-scoped project interpreter/root, set once from initializationOptions."""

    def test_defaults_to_none(self) -> None:
        settings = Settings()
        assert settings.project_interpreter is None
        assert settings.project_root is None

    def test_update_launch_context_populates_fields(self) -> None:
        settings = Settings()
        settings.update_launch_context(
            {"projectInterpreter": "/venv/bin/python", "projectRoot": "/home/me/proj"}
        )
        assert settings.project_interpreter == "/venv/bin/python"
        assert settings.project_root == "/home/me/proj"

    def test_update_launch_context_clears_on_empty_or_missing(self) -> None:
        settings = Settings(project_interpreter="/x", project_root="/y")
        # Empty string and absent key both clear to None (fall back to the server's own env).
        settings.update_launch_context({"projectInterpreter": ""})
        assert settings.project_interpreter is None
        assert settings.project_root is None

    def test_domain_update_does_not_touch_launch_fields(self) -> None:
        """The camelCase domain update() loop must ignore projectInterpreter/projectRoot."""
        settings = Settings()
        settings.update({"projectInterpreter": "/venv/bin/python", "mypyEnabled": False})
        assert settings.project_interpreter is None
        assert settings.mypy_enabled is False

    def test_launch_update_does_not_touch_domain_fields(self) -> None:
        settings = Settings(mypy_enabled=True)
        settings.update_launch_context(
            {"projectInterpreter": "/p", "mypyEnabled": False, "projectRoot": "/r"}
        )
        assert settings.mypy_enabled is True


class TestServerSettingsRefresh:
    """Tests for LSP configuration handling in server handlers."""

    async def test_did_change_configuration_prefers_inline_settings(
        self, lsp_server: FangtypeServer
    ) -> None:
        """Configuration-change payload should update settings without a pull."""
        params = types.DidChangeConfigurationParams(
            settings={"fangtype": {"crossFileContractsEnabled": False}}
        )

        await lsp_server.did_change_configuration(params)

        assert lsp_server.settings.cross_file_contracts_enabled is False

    async def test_did_change_configuration_keeps_current_on_empty_payload(
        self, lsp_server: FangtypeServer
    ) -> None:
        """An empty payload must not pull config and must leave settings unchanged."""
        lsp_server.settings.cross_file_contracts_enabled = False  # marker to detect change
        params = types.DidChangeConfigurationParams(settings={})

        await lsp_server.did_change_configuration(params)

        assert lsp_server.settings.cross_file_contracts_enabled is False

    async def test_did_change_configuration_accepts_per_folder_array(
        self, lsp_server: FangtypeServer
    ) -> None:
        """A per-folder settings array (flat camelCase keys) updates settings, no config pull."""
        params = types.DidChangeConfigurationParams(
            settings=[{"crossFileContractsEnabled": False, "cwd": "/w", "args": []}]
        )

        await lsp_server.did_change_configuration(params)

        assert lsp_server.settings.cross_file_contracts_enabled is False


class TestInitializeOptionsPush:
    """The ``INITIALIZE`` handler applies pushed settings."""

    async def test_initialize_applies_pushed_settings(self, lsp_server: FangtypeServer) -> None:
        """A ``{settings: {...}}`` payload updates the server's Settings."""
        params = types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            initialization_options={
                "settings": {
                    "mypyEnabled": False,
                    "diagnosticSeverity": "warning",
                }
            },
        )

        await lsp_server.initialize(params)

        assert lsp_server.settings.mypy_enabled is False
        assert lsp_server.settings.diagnostic_severity == "warning"

    async def test_initialize_accepts_per_folder_settings_array(
        self, lsp_server: FangtypeServer
    ) -> None:
        """A per-folder ``settings`` array applies the first entry."""
        params = types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            initialization_options={"settings": [{"crossFileContractsEnabled": False}]},
        )

        await lsp_server.initialize(params)

        assert lsp_server.settings.cross_file_contracts_enabled is False

    async def test_initialize_falls_back_to_global_settings(
        self, lsp_server: FangtypeServer
    ) -> None:
        """A ``{globalSettings: {...}}`` payload is applied when no per-folder settings exist."""
        params = types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            initialization_options={"globalSettings": {"crossFileContractsEnabled": False}},
        )

        await lsp_server.initialize(params)

        assert lsp_server.settings.cross_file_contracts_enabled is False

    async def test_initialize_without_options_leaves_defaults(
        self, lsp_server: FangtypeServer
    ) -> None:
        """Absent ``initializationOptions`` must leave settings at their defaults."""
        params = types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            initialization_options=None,
        )

        await lsp_server.initialize(params)

        assert lsp_server.settings.cross_file_contracts_enabled is True

    async def test_initialize_reads_launch_context(self, lsp_server: FangtypeServer) -> None:
        """``projectInterpreter``/``projectRoot`` ride alongside ``settings`` at initialize."""
        params = types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            initialization_options={
                "settings": {"mypyEnabled": False},
                "projectInterpreter": "/venv/bin/python",
                "projectRoot": "/home/me/proj",
            },
        )

        await lsp_server.initialize(params)

        assert lsp_server.settings.project_interpreter == "/venv/bin/python"
        assert lsp_server.settings.project_root == "/home/me/proj"
        assert lsp_server.settings.mypy_enabled is False
