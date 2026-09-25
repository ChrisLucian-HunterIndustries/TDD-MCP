"""Registry of supported languages. Add a `LanguageAdapter` here to support another language."""

from __future__ import annotations

from typing import Literal

from tdd_mcp.languages.base import LanguageAdapter
from tdd_mcp.languages.python import PythonAdapter

ADAPTERS: dict[str, LanguageAdapter] = {
    adapter.name: adapter for adapter in (PythonAdapter(),)
}

LanguageName = Literal[tuple(ADAPTERS)]
