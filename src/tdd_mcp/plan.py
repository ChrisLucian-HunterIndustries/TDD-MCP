"""The checklist of tests planned before a TDD session writes any code."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tdd_mcp.cycle import Phase


class PlanError(ValueError):
    """Raised when a test plan is incomplete or invalid."""


@dataclass(frozen=True)
class PlannedTest:
    name: str
    arrange: str
    act: str
    assertion: str


class Checklist:
    def __init__(self, tests: Sequence[PlannedTest]) -> None:
        if not tests:
            raise PlanError("A plan needs at least one test.")
        for test in tests:
            if not test.name.strip():
                raise PlanError("A planned test has no name.")
            parts = {"arrange": test.arrange, "act": test.act, "assert": test.assertion}
            missing = [part for part, text in parts.items() if not text.strip()]
            if missing:
                raise PlanError(f"{test.name!r} has no {' or '.join(missing)}.")
            if [t.name for t in tests].count(test.name) > 1:
                raise PlanError(f"{test.name!r} is planned twice.")
        self.tests = tuple(tests)
        self.done = 0

    @property
    def current(self) -> PlannedTest | None:
        return self.tests[self.done] if self.done < len(self.tests) else None

    def check_off(self) -> None:
        self.done += 1

    def reminder(self, phase: Phase) -> str:
        lines = [f"Test plan ({self.done} of {len(self.tests)} done):"]
        lines += [
            f"{_mark(number, self.done)} {test.name}"
            for number, test in enumerate(self.tests)
        ]
        step = _step(phase, self.current)
        return (
            "".join(f"{line}\n" for line in lines)
            + f"Next TDD step: {step} {ONLY_WHAT_IS_NEEDED}"
        )


ONLY_WHAT_IS_NEEDED = "Do only as much as this step needs, and no more."


def _mark(number: int, done: int) -> str:
    if number < done:
        return "[x]"
    return "[>]" if number == done else "[ ]"


def _step(phase: Phase, test: PlannedTest | None) -> str:
    if test is None:
        return (
            "every planned test is done. If the task still lacks a test, call "
            "plan_tests with only the missing ones; otherwise the task is finished."
        )
    if phase is Phase.GREEN:
        return (
            f"make {test.name!r} pass with only the production code its assert "
            f"needs ({test.assertion}); write nothing for the tests still waiting."
        )
    if phase is Phase.REFACTOR:
        return (
            "tidy the code without adding behaviour, commit, then call "
            f"advance_tdd_phase, which checks off {test.name!r}."
        )
    return (
        f"write only the test {test.name!r}, with that name in its test name, "
        "nothing else. "
        f"Arrange: {test.arrange}. Act: {test.act}. Assert: {test.assertion}."
    )
