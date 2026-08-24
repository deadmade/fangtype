"""Tests for mypy-based type validator."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fangtype.utils.settings import Settings
from fangtype.validation import MypyTypeValidator
from fangtype.validation.mypy_runner import MypyRunner


@pytest.fixture
def validator():
    """Create a MypyTypeValidator instance, releasing its resources after use."""
    validator = MypyTypeValidator(Settings())
    yield validator
    validator.close()


_PROTOCOL_SRC = (
    "from typing import Protocol\n\n\nclass MyProtocol(Protocol):\n    def m(self) -> int: ...\n"
)


async def test_validate_file_full_no_errors(validator):
    """Test validate_file_full returns empty list for valid code."""
    source = """
x: int = 42
y: str = "hello"
z: list[int] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) == 0


async def test_validate_file_full_single_error(validator):
    """Test validate_file_full detects a single type error."""
    source = """
x: str = 42
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert diagnostics[0].severity == "error"
    assert (
        "incompatible" in diagnostics[0].message.lower()
        or "assignment" in diagnostics[0].message.lower()
    )


async def test_validate_file_full_multiple_errors(validator):
    """Test validate_file_full detects multiple errors."""
    source = """
x: str = 42
y: int = "hello"
z: list[str] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 3


async def test_validate_file_full_line_numbers(validator):
    """Test validate_file_full returns correct line numbers."""
    source = """
x: int = 42
y: str = 123
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Error should be on line 3 (1-based, as mypy reports)
    assert any(d.line == 3 for d in diagnostics)


async def test_validate_file_full_reports_the_real_column(validator):
    """M16: real mypy run -> the column lands on the offending token, not on column 0."""
    source = 'def f() -> int:\n    return "wrong"\n'

    diagnostics = await validator.validate_file_full(source)

    offending = [d for d in diagnostics if d.line == 2]
    assert offending, diagnostics
    # `"wrong"` starts at 0-based column 11 (4 spaces + `return `).
    assert offending[0].column == 11


async def test_validate_file_full_with_imports(validator):
    """Test validate_file_full works with imports."""
    source = """
from typing import List

x: List[int] = [1, 2, 3]
y: List[str] = [1, 2, 3]
"""
    diagnostics = await validator.validate_file_full(source)
    # Should detect the wrong-element error in y (mypy: "List item 0 ...").
    assert len(diagnostics) >= 1
    assert any("List item 0" in d.message for d in diagnostics)


async def test_validate_file_full_undefined_name(validator):
    """Test validate_file_full detects undefined names."""
    source = """
x = undefined_variable
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    assert "not defined" in diagnostics[0].message


async def test_validate_file_full_function_errors(validator):
    """Test validate_file_full detects function type errors."""
    source = """
def foo(x: int) -> str:
    return x

result = foo("wrong")
"""
    diagnostics = await validator.validate_file_full(source)
    # Should detect both return type error and argument type error
    assert len(diagnostics) >= 2


async def test_validate_file_full_syntax_error(validator):
    """Test validate_file_full handles syntax errors."""
    source = """
def foo(
"""
    diagnostics = await validator.validate_file_full(source)
    # Should report syntax error
    assert len(diagnostics) >= 1


async def test_validate_file_full_error_codes(validator):
    """Test validate_file_full extracts error codes."""
    source = """
x: str = 42
"""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) >= 1
    # Mypy should provide error codes for most errors
    assert any(d.error_code is not None for d in diagnostics)


async def test_validate_file_full_empty_source(validator):
    """Test validate_file_full with empty source."""
    source = ""
    diagnostics = await validator.validate_file_full(source)
    assert len(diagnostics) == 0


async def test_validate_file_full_offloads_only_mypy_run(validator):
    """Test validate_file_full wraps only mypy execution in asyncio.to_thread."""
    source = "x: int = 1"

    with patch(
        "fangtype.validation.mypy_validator.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = []

        diagnostics = await validator.validate_file_full(source)

    assert diagnostics == []
    mock_to_thread.assert_awaited_once()
    assert mock_to_thread.await_args is not None
    called_callable, called_args = mock_to_thread.await_args.args
    assert called_callable.__func__ is validator._validate_file_full_sync.__func__
    assert called_args == source


async def test_validate_file_full_reraises_cancelled_error(validator):
    """CancelledError must propagate so server cancellation branches stay live."""
    with patch(
        "fangtype.validation.mypy_validator.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.side_effect = asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await validator.validate_file_full("x = 1\n")


def test_close_terminates_the_runner_and_is_idempotent():
    """close() must call the built runner's close() and clear it; a second call must not raise."""
    validator = MypyTypeValidator(Settings())
    with patch("fangtype.validation.mypy_validator.MypyRunner") as mock_runner_cls:
        mock_runner = mock_runner_cls.return_value
        validator._ensure_runner()

        validator.close()
        mock_runner.close.assert_called_once()
        assert validator._runner is None

        validator.close()  # double shutdown: no runner left, must not raise or re-invoke close()
        mock_runner.close.assert_called_once()


def test_ensure_runner_builds_exactly_one_runner_under_concurrency():
    """S6.2: N concurrent _run_mypy_sync calls must construct exactly one MypyRunner."""
    validator = MypyTypeValidator(Settings())
    construction_count = 0
    count_lock = threading.Lock()

    class TrackedRunner:
        def __init__(self, *args, **kwargs):
            nonlocal construction_count
            with count_lock:
                construction_count += 1
            # Widen the check-then-construct window so an unlocked race actually manifests.
            threading.Event().wait(0.05)

        def run(self, code):
            return ("", "", 0)

        def close(self):
            pass

    try:
        with (
            patch("fangtype.validation.mypy_validator.MypyRunner", TrackedRunner),
            ThreadPoolExecutor(max_workers=8) as pool,
        ):
            list(pool.map(lambda _: validator._run_mypy_sync("x = 1\n"), range(8)))

        assert construction_count == 1
    finally:
        validator.close()


def test_parse_mypy_output_parses_string_prefix():
    """Regression #14: _parse_mypy_output parses mypy's <string> source prefix."""
    validator = MypyTypeValidator(Settings())
    try:
        output = (
            "<string>:5:11: error: Incompatible types in assignment "
            '(expression has type "str", variable has type "int")  [assignment]'
        )
        diagnostics = validator._parse_mypy_output(output)
    finally:
        validator.close()

    assert len(diagnostics) == 1
    assert diagnostics[0].line == 5
    assert diagnostics[0].column == 10  # mypy's 1-based 11 -> 0-based
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].error_code == "assignment"


def test_parse_mypy_output_ignores_foreign_file_line():
    """Regression #14 (RED): _parse_mypy_output ignores foreign-file diagnostic lines."""
    validator = MypyTypeValidator(Settings())
    try:
        output = "utils.py:40: error: something wrong  [assignment]"
        diagnostics = validator._parse_mypy_output(output)
    finally:
        validator.close()

    assert diagnostics == []


def test_parse_mypy_output_not_spoofed_by_foreign_line():
    """Regression #14: a followed project file's diagnostic is dropped, only `<string>` survives."""
    validator = MypyTypeValidator(Settings())
    try:
        # A followed project file errors on line 7, coinciding with a real line in the checked file.
        output = (
            "utils.py:7: error: Incompatible types in assignment  [assignment]\n"
            "<string>:7: error: Incompatible types in assignment  [assignment]"
        )
        diagnostics = validator._parse_mypy_output(output)
    finally:
        validator.close()

    # Only the real probe-source diagnostic on line 7 survives; the foreign one is dropped.
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 7
    validator.close()


class TestMypyProjectAwareFlags:
    """Flags carry --python-executable/--python-version so a managed venv stays project-aware."""

    def test_flags_omit_executable_and_default_version_without_project_interpreter(self) -> None:
        validator = MypyTypeValidator(Settings())
        flags = validator._mypy_flags()
        assert "--python-executable" not in flags
        assert flags[flags.index("--python-version") + 1] == "3.12"

    def test_flags_include_executable_and_probed_version_when_set(self) -> None:
        validator = MypyTypeValidator(Settings(project_interpreter="/venv/bin/python"))
        with patch("fangtype.validation.mypy_validator._probe_python_version", return_value="3.13"):
            flags = validator._mypy_flags()
        assert flags[flags.index("--python-executable") + 1] == "/venv/bin/python"
        assert flags[flags.index("--python-version") + 1] == "3.13"

    def test_version_defaults_when_probe_fails(self) -> None:
        validator = MypyTypeValidator(Settings(project_interpreter="/venv/bin/python"))
        with patch("fangtype.validation.mypy_validator._probe_python_version", return_value=None):
            flags = validator._mypy_flags()
        assert flags[flags.index("--python-version") + 1] == "3.12"


def test_probe_python_version_reads_real_interpreter() -> None:
    import re
    import sys

    from fangtype.validation.mypy_validator import _probe_python_version

    version = _probe_python_version(sys.executable)
    assert version is not None and re.fullmatch(r"\d+\.\d+", version)


def test_probe_python_version_returns_none_for_missing_interpreter() -> None:
    from fangtype.validation.mypy_validator import _probe_python_version

    assert _probe_python_version("/no/such/python-xyz-42") is None


def test_probe_python_version_reads_pyvenv_cfg_without_subprocess(tmp_path: Path) -> None:
    """A venv interpreter resolves via pyvenv.cfg — no subprocess spawned (the Windows 10s stall)."""
    from unittest.mock import patch

    from fangtype.validation.mypy_validator import _probe_python_version

    (tmp_path / "pyvenv.cfg").write_text(
        "home = /usr/bin\ninclude-system-site-packages = false\nversion_info = 3.14.0a1\n"
    )
    interpreter = str(tmp_path / "Scripts" / "python.exe")  # Windows layout: cfg is two dirs up

    with patch("fangtype.validation.mypy_validator.subprocess.run") as run:
        assert _probe_python_version(interpreter) == "3.14"
        run.assert_not_called()


class TestProjectImports:
    """mypy must resolve first-party project imports rather than see them as Any."""

    @staticmethod
    def _project(tmp_path: Path) -> str:
        pkg = tmp_path / "myapp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "models.py").write_text("class Widget:\n    size: int\n")
        return "from myapp.models import Widget\n"

    async def test_project_type_is_resolved_and_checked(self, tmp_path, monkeypatch):
        """A project type validates, and a misuse of it is rejected: proves imports are followed."""
        monkeypatch.delenv("MYPYPATH", raising=False)
        source = self._project(tmp_path)
        settings = Settings()
        settings.update_launch_context({"projectRoot": str(tmp_path)})
        validator = MypyTypeValidator(settings)
        try:
            good = await validator.validate_file_full(source + "good: Widget\n")
            bad = await validator.validate_file_full(source + "bad: Widget[int]\n")
            junk = await validator.validate_file_full(source + "junk: Nonsense\n")
        finally:
            validator.close()

        assert not good, "a real project type must validate"
        # Widget[int] is only catchable if mypy actually resolved Widget rather than seeing Any.
        assert bad, "project import was not followed (resolved as Any)"
        assert junk

    async def test_project_import_is_not_reported_as_a_diagnostic(self, tmp_path, monkeypatch):
        """Importing a project module must not raise import-not-found on the user's own file."""
        monkeypatch.delenv("MYPYPATH", raising=False)
        source = self._project(tmp_path) + "w = Widget()\n"
        settings = Settings()
        settings.update_launch_context({"projectRoot": str(tmp_path)})
        validator = MypyTypeValidator(settings)
        try:
            diagnostics = await validator.validate_file_full(source)
        finally:
            validator.close()

        assert [d.message for d in diagnostics] == []


_RUNNER_FLAGS = [
    "--no-error-summary",
    "--no-color-output",
    "--show-column-numbers",
    "--follow-imports=silent",
    "--python-version",
    "3.12",
]


class TestMypyRunnerWorker:
    """The persistent worker in MypyRunner: reuse, recycle, crash recovery, timeout fail-open."""

    def _runner(self, cache_key: str = "worker-test") -> MypyRunner:
        return MypyRunner(flags=_RUNNER_FLAGS, cache_key=cache_key)

    def test_worker_is_reused_across_runs(self):
        """Two runs share one worker process (the whole point — no per-call respawn)."""
        runner = self._runner()
        try:
            runner.run("x: int")
            first = runner._proc
            runner.run("y: str")
            assert runner._proc is first
            assert runner._proc is not None
            assert runner._proc.poll() is None
            assert runner._run_count == 2
        finally:
            runner.close()

    def test_worker_recycles_after_run_limit(self, monkeypatch):
        """Hitting _RECYCLE_AFTER_RUNS replaces the worker to bound the RSS leak."""
        from fangtype.validation import mypy_runner

        monkeypatch.setattr(mypy_runner, "_RECYCLE_AFTER_RUNS", 2)
        runner = self._runner()
        try:
            runner.run("a: int")
            runner.run("b: int")  # now at the limit
            recycled_from = runner._proc
            runner.run("c: int")  # triggers kill + respawn before running
            assert runner._proc is not recycled_from
            assert runner._proc is not None
            assert runner._proc.poll() is None
        finally:
            runner.close()

    def test_worker_respawns_after_crash(self):
        """If the worker dies mid-life, the next run respawns and still returns a verdict."""
        runner = self._runner()
        try:
            runner.run("x: int")
            assert runner._proc is not None
            runner._proc.kill()
            runner._proc.wait()
            out, _err, code = runner.run("y: NotARealType")
            assert code == 1  # error verdict survives the respawn
            assert "NotARealType" in out
        finally:
            runner.close()

    def test_timeout_fails_open(self, monkeypatch):
        """A wedged run returns exit 2 (upstream treats empty-stdout non-zero as fail-open)."""
        from fangtype.validation import mypy_runner

        runner = self._runner()
        try:
            monkeypatch.setattr(mypy_runner, "_RUN_TIMEOUT_SECONDS", 0.001)
            out, err, code = runner.run("x: int")
            assert (out, code) == ("", 2)
            assert "timed out" in err
        finally:
            runner.close()

    def test_close_is_idempotent(self):
        """close() twice must not raise even with a live worker handle."""
        runner = self._runner()
        runner.run("x: int")
        runner.close()
        runner.close()
        assert runner._proc is None
