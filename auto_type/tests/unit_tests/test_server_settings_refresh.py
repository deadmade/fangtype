"""Tests for server-side configuration refresh behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from lsprotocol import types

from auto_type.container import get_container
from auto_type.server import _refresh_settings, did_change_configuration
from auto_type.utils.settings import Settings


class TestServerSettingsRefresh:
    """Tests for LSP configuration handling in server handlers."""

    async def test_refresh_settings_uses_workspace_configuration_async(self) -> None:
        """Refresh should apply returned autoType settings."""
        ls = MagicMock()
        ls.workspace_configuration_async = AsyncMock(
            return_value=[
                {
                    "inlayHintsEnabled": False,
                    "mypyEnabled": False,
                    "mypyInferenceValidationEnabled": True,
                }
            ]
        )

        await _refresh_settings(ls)

        ls.workspace_configuration_async.assert_awaited_once()
        settings = get_container().get(Settings)
        assert settings.inlay_hints_enabled is False
        assert settings.mypy_enabled is False
        assert settings.mypy_inference_validation_enabled is True

    async def test_refresh_settings_handles_empty_payload(self) -> None:
        """Refresh should tolerate empty client configuration responses."""
        ls = MagicMock()
        ls.workspace_configuration_async = AsyncMock(return_value=[])

        await _refresh_settings(ls)

        settings = get_container().get(Settings)
        assert settings.inlay_hints_enabled is True
        assert settings.mypy_enabled is True
        assert settings.mypy_inference_validation_enabled is True

    async def test_did_change_configuration_prefers_inline_settings(self) -> None:
        """Configuration-change payload should update settings without refetch."""
        ls = MagicMock()
        ls.workspace_configuration_async = AsyncMock()
        params = types.DidChangeConfigurationParams(settings={"autoType": {"skipAnnotated": False}})

        await did_change_configuration(ls, params)

        ls.workspace_configuration_async.assert_not_awaited()
        settings = get_container().get(Settings)
        assert settings.skip_annotated is False

    async def test_did_change_configuration_refetches_when_payload_empty(self) -> None:
        """Empty payload should trigger workspace configuration fetch."""
        ls = MagicMock()
        ls.workspace_configuration_async = AsyncMock(return_value=[{"showUsageHints": False}])
        params = types.DidChangeConfigurationParams(settings={})

        await did_change_configuration(ls, params)

        ls.workspace_configuration_async.assert_awaited_once()
        settings = get_container().get(Settings)
        assert settings.show_usage_hints is False
