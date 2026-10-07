"""The checklist of tests planned before a TDD session writes any code."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedTest:
    name: str
    arrange: str
    act: str
    assertion: str


class Checklist:
    def __init__(self, tests: Sequence[PlannedTest]) -> None:
        self.tests = tuple(tests)
        self.done = 0

    @property
    def current(self) -> PlannedTest | None:
        return self.tests[self.done] if self.done < len(self.tests) else None

    def check_off(self) -> None:
        self.done += 1
