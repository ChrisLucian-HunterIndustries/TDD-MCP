from pathlib import PurePath

import pytest

from tdd_mcp.cycle import FileKind
from tdd_mcp.languages.typescript import TypeScriptAdapter

adapter = TypeScriptAdapter()


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("src/calc.test.ts", FileKind.TEST),
        ("src/calc.spec.tsx", FileKind.TEST),
        ("calc.test.mts", FileKind.TEST),
        ("src/__tests__/calc.ts", FileKind.TEST),
        ("test/helpers.ts", FileKind.TEST),
        ("tests/setup.js", FileKind.TEST),
        ("src/calc.ts", FileKind.PRODUCTION),
        ("src/App.tsx", FileKind.PRODUCTION),
        ("src/types.d.ts", FileKind.PRODUCTION),
        ("src/testing.ts", FileKind.PRODUCTION),
        ("src/latest.ts", FileKind.PRODUCTION),
        ("index.js", FileKind.PRODUCTION),
        ("lib/util.cjs", FileKind.PRODUCTION),
        ("vitest.config.ts", FileKind.PRODUCTION),
        ("package.json", FileKind.OTHER),
        ("tsconfig.json", FileKind.OTHER),
        ("README.md", FileKind.OTHER),
        ("src/calc.py", FileKind.OTHER),
    ],
)
def test_classify(path: str, kind: FileKind):
    assert adapter.classify(PurePath(path)) is kind


def test_name():
    assert adapter.name == "typescript"
