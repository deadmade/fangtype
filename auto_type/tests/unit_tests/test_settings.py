"""Tests for server settings parsing and validation."""

from auto_type.utils.settings import Settings


class TestSettingsUpdate:
    """Tests for Settings.update()."""

    def test_updates_from_vscode_section_payload(self) -> None:
        """CamelCase keys from VSCode should map to snake_case fields."""
        settings = Settings()

        settings.update(
            {
                "inlayHintsEnabled": False,
                "showUsageHints": False,
                "preferModernTypes": False,
                "mypyEnabled": False,
                "mypyInferenceValidationEnabled": True,
                "diagnosticSeverity": "warning",
                "skipAnnotated": False,
            }
        )

        assert settings.inlay_hints_enabled is False
        assert settings.show_usage_hints is False
        assert settings.prefer_modern_types is False
        assert settings.mypy_enabled is False
        assert settings.mypy_inference_validation_enabled is True
        assert settings.diagnostic_severity == "warning"
        assert settings.skip_annotated is False

    def test_updates_from_nested_autotype_payload(self) -> None:
        """Nested autoType payloads should also be supported."""
        settings = Settings()

        settings.update({"autoType": {"showUsageHints": False}})

        assert settings.show_usage_hints is False

    def test_ignores_invalid_value_types(self) -> None:
        """Invalid value types should not overwrite existing settings."""
        settings = Settings()

        settings.update(
            {
                "inlayHintsEnabled": "false",
                "mypyInferenceValidationEnabled": "true",
                "diagnosticSeverity": 123,
            }
        )

        assert settings.inlay_hints_enabled is True
        assert settings.mypy_inference_validation_enabled is True
        assert settings.diagnostic_severity == "information"

    def test_ignores_invalid_diagnostic_severity(self) -> None:
        """Invalid diagnostic severity should keep the previous value."""
        settings = Settings()

        settings.update({"diagnosticSeverity": "critical"})

        assert settings.diagnostic_severity == "information"
