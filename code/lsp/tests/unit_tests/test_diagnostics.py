"""Tests for diagnostic engine and mypy integration."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lsprotocol import types

from fangtype.diagnostics import DiagnosticEngine
from fangtype.protocols import TypeValidatorProtocol
from fangtype.utils.settings import Settings


@pytest.fixture
def mock_settings():
    """Create a default Settings instance."""
    return Settings()


@pytest.fixture
def mock_validator(mocker):
    """Create a mock TypeValidatorProtocol."""
    mock = mocker.MagicMock(spec=TypeValidatorProtocol)
    mock.validate_file_full = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def engine_with_mock(mock_validator, mock_settings):
    """Create a DiagnosticEngine with mocked validator and settings."""
    return DiagnosticEngine(mock_validator, mock_settings)


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

    async def test_diagnostic_columns_converted_to_utf16(self, engine_with_mock, mock_validator):
        """Astral char left of diagnostic shifts code-point cols 9..12 to UTF-16 10..13."""
        source = 's = "😀"; bad'  # 'bad' spans code points 9..12
        mock_diag = MagicMock()
        mock_diag.line = 1
        mock_diag.column = 9
        mock_diag.end_line = 1
        mock_diag.message = "err"
        mock_diag.severity = "error"
        mock_diag.error_code = "misc"
        mock_validator.validate_file_full.return_value = [mock_diag]

        diagnostics = await engine_with_mock.generate_diagnostics(source, "test.py")

        assert len(diagnostics) == 1
        rng = diagnostics[0].range
        assert (rng.start.character, rng.end.character) == (10, 13)

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


class TestDiagnosticsAsync:
    """Tests for non-blocking and debounced diagnostics."""

    def test_schedule_diagnostics_is_debounced(self) -> None:
        """Test that multiple schedule_diagnostics calls only result in one execution."""

        async def run_test() -> None:
            mock_validator = MagicMock()
            mock_validator.validate_file_full = AsyncMock(return_value=[])
            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            mock_ls.workspace.get_text_document.return_value.source = "x = 1"
            uri = "file:///test.py"

            # Schedule multiple times
            engine.schedule_diagnostics(mock_ls, uri)
            engine.schedule_diagnostics(mock_ls, uri)
            engine.schedule_diagnostics(mock_ls, uri)

            # Wait for more than 500ms
            await asyncio.sleep(0.7)

            # Should only have been called once despite 3 schedules
            assert mock_validator.validate_file_full.call_count == 1

        asyncio.run(run_test())

    def test_timer_pruned_after_it_fires(self) -> None:
        """A fired debounce timer's ``_timers`` entry is popped rather than leaking forever."""

        async def run_test() -> None:
            mock_validator = MagicMock()
            mock_validator.validate_file_full = AsyncMock(return_value=[])
            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            mock_ls.workspace.get_text_document.return_value.source = "x = 1"
            uri = "file:///test.py"

            engine.schedule_diagnostics(mock_ls, uri)
            assert uri in engine._timers

            await asyncio.sleep(0.7)

            assert uri not in engine._timers

        asyncio.run(run_test())

    def test_cancel_pending_cancels_and_pops_timer(self) -> None:
        """``cancel_pending`` (didClose) cancels a pending timer and pops it so it never fires."""

        async def run_test() -> None:
            mock_validator = MagicMock()
            mock_validator.validate_file_full = AsyncMock(return_value=[])
            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            uri = "file:///test.py"

            engine.schedule_diagnostics(mock_ls, uri)
            timer = engine._timers[uri]
            assert not timer.cancelled()

            engine.cancel_pending(uri)

            assert timer.cancelled()
            assert uri not in engine._timers

        asyncio.run(run_test())

    def test_cancel_pending_is_a_noop_for_unknown_uri(self) -> None:
        """Closing a document with no pending timer must not raise."""
        mock_validator = MagicMock()
        engine = DiagnosticEngine(mock_validator, Settings())

        engine.cancel_pending("file:///never-scheduled.py")  # must not raise

        assert engine._timers == {}

    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="Flaky timing test, fails in CI due to environment overhead",
    )
    def test_diagnostics_not_blocking_loop(self) -> None:
        """Test that slow diagnostics don't block the event loop."""

        async def run_test() -> None:
            mock_validator = MagicMock()

            async def slow_validate(source, file_path):
                await asyncio.to_thread(time.sleep, 0.5)  # Simulate CPU work in thread
                return []

            mock_validator.validate_file_full = AsyncMock(side_effect=slow_validate)

            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            mock_ls.workspace.get_text_document.return_value.source = "x = 1"
            uri = "file:///test.py"

            start_time = time.time()

            # Schedule diagnostics
            engine.schedule_diagnostics(mock_ls, uri)

            # While diagnostics are "running", the loop should be free
            for _ in range(5):
                await asyncio.sleep(0.1)

            elapsed = time.time() - start_time
            # Non-blocking takes ~0.5s (the sleeps) + overhead; blocking would take ~1.0s.
            assert elapsed < 0.9

        asyncio.run(run_test())

    def test_run_diagnostics_offloaded_to_thread(self) -> None:
        """Verify _run_diagnostics_async runs diagnostics then forces an inlay re-pull."""

        async def run_test() -> None:
            mock_validator = MagicMock()
            mock_validator.validate_file_full = AsyncMock(return_value=[])
            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            mock_ls.workspace.get_text_document.return_value.source = "x = 1"
            mock_ls.workspace_inlay_hint_refresh_async = AsyncMock()
            uri = "file:///test.py"

            with patch.object(engine, "run_diagnostics", new_callable=AsyncMock) as mock_run:
                await engine._run_diagnostics_async(mock_ls, uri)

                # Check if run_diagnostics was called
                mock_run.assert_called_once()
                args, _ = mock_run.call_args
                assert args[0] == mock_ls
                assert args[1] == uri
                # The debounced change path must settle inlay hints (unlike did_change itself).
                mock_ls.workspace_inlay_hint_refresh_async.assert_awaited_once_with(None)

        asyncio.run(run_test())
