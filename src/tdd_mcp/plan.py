"""The checklist of tests planned before a TDD session writes any code."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


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
