import sys
from pathlib import Path

from tdd_mcp.cycle import Outcome
from tdd_mcp.languages.base import run_suite

EXIT_OUTCOMES = {0: Outcome.PASSED, 1: Outcome.FAILED}


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_maps_exit_code_to_outcome_and_captures_output(tmp_path: Path):
    run = run_suite(
        _python("print('hi'); raise SystemExit(1)"), tmp_path, EXIT_OUTCOMES
    )
    assert run.outcome is Outcome.FAILED
    assert "hi" in run.output


def test_captures_stderr(tmp_path: Path):
    run = run_suite(
        _python("import sys; sys.stderr.write('oops')"), tmp_path, EXIT_OUTCOMES
    )
    assert run.outcome is Outcome.PASSED
    assert "oops" in run.output


def test_runs_in_given_directory(tmp_path: Path):
    run = run_suite(_python("import os; print(os.getcwd())"), tmp_path, EXIT_OUTCOMES)
    assert str(tmp_path) in run.output


def test_extra_env_is_added_to_inherited_environment(tmp_path: Path):
    code = "import os; print(os.environ['TDD_EXTRA'], 'PATH' in os.environ)"
    run = run_suite(_python(code), tmp_path, EXIT_OUTCOMES, env={"TDD_EXTRA": "yes"})
    assert "yes True" in run.output


def test_output_is_decoded_as_utf8(tmp_path: Path):
    code = "import sys; sys.stdout.buffer.write('\u2713 \u276f'.encode('utf-8'))"
    run = run_suite(_python(code), tmp_path, EXIT_OUTCOMES)
    assert "\u2713 \u276f" in run.output


def test_unmapped_exit_code_is_an_error(tmp_path: Path):
    run = run_suite(_python("raise SystemExit(7)"), tmp_path, EXIT_OUTCOMES)
    assert run.outcome is Outcome.ERROR
    assert "exit code 7" in run.output


def test_missing_executable_is_an_error(tmp_path: Path):
    run = run_suite(["definitely-not-a-real-executable-xyz"], tmp_path, EXIT_OUTCOMES)
    assert run.outcome is Outcome.ERROR


def test_timeout_is_an_error(tmp_path: Path):
    run = run_suite(
        _python("import time; time.sleep(5)"), tmp_path, EXIT_OUTCOMES, timeout=0.5
    )
    assert run.outcome is Outcome.ERROR
    assert "timed out" in run.output
