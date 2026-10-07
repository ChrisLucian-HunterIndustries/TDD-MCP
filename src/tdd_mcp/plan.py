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

    @property
    def current(self) -> PlannedTest:
        return self.tests[0]
