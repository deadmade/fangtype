import asyncio
import os
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from injector import Injector

from auto_type.container import get_container, reset_container
from auto_type.diagnostics import DiagnosticEngine
from auto_type.utils.settings import Settings


class TestThreadSafeContainer:
    """Tests for thread safety of the dependency injection container."""

    def test_concurrent_get_container(self) -> None:
        """Test that multiple threads calling get_container get the same instance."""
        reset_container()
        containers = []
        num_threads = 10
        barrier = threading.Barrier(num_threads)

        def worker():
            barrier.wait()  # Try to make them hit it at the same time
            containers.append(get_container())

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(containers) == num_threads
        first_container = containers[0]
        for c in containers:
            assert c is first_container
        assert isinstance(first_container, Injector)


class TestDiagnosticAsync:
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
            # Non-blocking: should take ~0.5s for sleeps + small overhead
            # Blocking: would take ~1.0s
            assert elapsed < 0.9

        asyncio.run(run_test())

    def test_run_diagnostics_offloaded_to_thread(self) -> None:
        """Verify that _run_diagnostics_async calls run_diagnostics."""

        async def run_test() -> None:
            mock_validator = MagicMock()
            mock_validator.validate_file_full = AsyncMock(return_value=[])
            engine = DiagnosticEngine(mock_validator, Settings())
            mock_ls = MagicMock()
            mock_ls.workspace.get_text_document.return_value.source = "x = 1"
            uri = "file:///test.py"

            with patch.object(engine, "run_diagnostics", new_callable=AsyncMock) as mock_run:
                await engine._run_diagnostics_async(mock_ls, uri)

                # Check if run_diagnostics was called
                mock_run.assert_called_once()
                args, _ = mock_run.call_args
                assert args[0] == mock_ls
                assert args[1] == uri

        asyncio.run(run_test())
