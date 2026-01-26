"""Tests for diagnostic engine and mypy integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from lsprotocol import types

from auto_type.diagnostics import DiagnosticEngine
from auto_type.protocols import TypeValidatorProtocol
from auto_type.validation import MypyTypeValidator


@pytest.fixture
def mock_validator(mocker):
    """Create a mock TypeValidatorProtocol."""
    mock = mocker.MagicMock(spec=TypeValidatorProtocol)
    mock.validate_file_full = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def engine_with_mock(mock_validator):
    """Create a DiagnosticEngine with mocked validator."""
    return DiagnosticEngine(mock_validator)


@pytest.fixture
def real_validator():
    """Create a real MypyTypeValidator instance."""
    return MypyTypeValidator()


class TestDiagnosticEngineUnit:
    """Unit tests for DiagnosticEngine logic using mocked validator."""

    async def test_generate_diagnostics_empty(self, engine_with_mock, mock_validator):
        """Test that empty validator response leads to empty diagnostics."""
        mock_validator.validate_file_full.return_value = []
        diagnostics = await engine_with_mock.generate_diagnostics("source", "test.py")
        assert len(diagnostics) == 0

    async def test_generate_diagnostics_conversion(self, engine_with_mock, mock_validator):
        """Test conversion of validator diagnostics to LSP diagnostics."""
        # Setup mock validator response
        mock_diag = MagicMock()
        mock_diag.line = 1  # 1-based
        mock_diag.column = 0
        mock_diag.end_line = 1
        mock_diag.end_column = 10
        mock_diag.message = "Test error"
        mock_diag.severity = "error"
        mock_diag.error_code = "misc"

        mock_validator.validate_file_full.return_value = [mock_diag]

        diagnostics = await engine_with_mock.generate_diagnostics("source", "test.py")

        assert len(diagnostics) == 1
        d = diagnostics[0]
        assert d.range.start.line == 0  # 0-based
        assert d.message == "Test error"
        assert d.severity == types.DiagnosticSeverity.Error
        assert d.source == "mypy"
        assert d.code == "misc"

    @pytest.mark.parametrize(
        "severity_str, expected_severity",
        [
            ("error", types.DiagnosticSeverity.Error),
            ("note", types.DiagnosticSeverity.Information),
            ("warning", types.DiagnosticSeverity.Warning),
            ("unknown", types.DiagnosticSeverity.Error),  # Default fallback
        ],
    )
    async def test_severity_mapping(
        self, engine_with_mock, mock_validator, severity_str, expected_severity
    ):
        """Test mapping of string severities to LSP enums."""
        mock_diag = MagicMock()
        mock_diag.line = 1
        mock_diag.column = 0
        mock_diag.end_line = 1
        mock_diag.end_column = 5
        mock_diag.message = "Msg"
        mock_diag.severity = severity_str

        mock_validator.validate_file_full.return_value = [mock_diag]

        diagnostics = await engine_with_mock.generate_diagnostics("src", "f.py")
        assert len(diagnostics) == 1
        assert diagnostics[0].severity == expected_severity

    async def test_diagnostic_for_missing_types(self, engine_with_mock, mock_validator):
        """Test special handling for missing type annotations."""
        mock_diag = MagicMock()
        mock_diag.line = 1
        mock_diag.column = 0
        mock_diag.end_line = 1
        mock_diag.end_column = 10
        mock_diag.message = "Function is missing a return type annotation"
        mock_diag.severity = "error"  # Mypy reports as error usually
        mock_diag.error_code = "no-untyped-def"

        mock_validator.validate_file_full.return_value = [mock_diag]

        diagnostics = await engine_with_mock.generate_diagnostics("src", "f.py")

        assert len(diagnostics) == 1


class TestMypyTypeValidatorIntegration:
    """Integration tests using real MypyTypeValidator."""

    async def test_real_mypy_validation(self, real_validator):
        """Test running real mypy against a string."""
        source = "x: int = 'string'"
        diagnostics = await real_validator.validate_file_full(source)

        assert len(diagnostics) > 0
        assert any("Incompatible types" in d.message for d in diagnostics)

    async def test_valid_code_no_errors(self, real_validator):
        """Test valid code produces no errors."""
        source = "x: int = 1"
        diagnostics = await real_validator.validate_file_full(source)
        assert len(diagnostics) == 0

    async def test_syntax_error(self, real_validator):
        """Test handling of syntax errors."""
        source = "def ("
        diagnostics = await real_validator.validate_file_full(source)
        assert len(diagnostics) > 0

    @pytest.mark.parametrize(
        "source, expected_msg_part",
        [
            ("x = undefined_var", "not defined"),
            ("from typing import List; x: List[int] = ['s']", "List item 0"),
        ],
    )
    async def test_various_errors(self, real_validator, source, expected_msg_part):
        """Test various error scenarios."""
        diagnostics = await real_validator.validate_file_full(source)
        assert any(expected_msg_part in d.message for d in diagnostics)
