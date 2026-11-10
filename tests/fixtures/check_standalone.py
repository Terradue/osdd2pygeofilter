"""Exercise a generated module with generator-only dependencies unavailable.

Executed in a fresh isolated Python process by test_converter.py.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import sys
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType


class BlockGeneratorImports(importlib.abc.MetaPathFinder):
    """Simulate deploying only the evaluator and its runtime dependencies."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        """Reject generator dependencies, including transitive imports."""
        if fullname.split(".", 1)[0] in {"osdd2pygeofilter", "jinja2", "lxml"}:
            raise ModuleNotFoundError(f"Generator dependency unavailable: {fullname}")
        return None


class Adapter(Protocol):
    """Public generated APIs exercised by this deployment check."""

    def from_cql2_text(self, expression: str) -> str: ...

    def from_cql2_json(self, expression: str) -> str: ...

    def build_url(self, parameters: Mapping[str, str]) -> str: ...


def check_adapter(adapter: Adapter) -> None:
    """Verify conversion and extension validation without the generator."""
    query = adapter.from_cql2_text(
        "searchTerms = 'ice & snow' AND \"earth:cloudCover\" >= 10 "
        'AND "earth:cloudCover" < 20 AND S_INTERSECTS("g:geometry", POINT(10 20))'
    )
    assert parse_qs(query) == {
        "q": ["ice & snow"],
        "cloud": ["[10,20["],
        "geometry": ["POINT (10.0 20.0)"],
    }
    assert adapter.from_cql2_json('{"op":"=","args":[{"property":"count"},4]}') == "n=4"
    assert adapter.build_url({"q": "ice & snow"}) == "https://example.test/?q=ice%20%26%20snow"
    for parameters in (
        {"n": "3"},
        {"cloud": "101"},
        {"geometry": "invalid"},
        {"start": "2025-02-30T00:00:00Z"},
        {"packing": "invalid"},
        {"set": "invalid"},
    ):
        try:
            adapter.build_url(parameters)
        except ValueError:
            continue
        raise AssertionError(f"Invalid parameters accepted: {parameters}")


def main() -> None:
    """Import the file passed on the command line and check its behavior."""
    sys.meta_path.insert(0, BlockGeneratorImports())
    specification = importlib.util.spec_from_file_location("standalone", sys.argv[1])
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules["standalone"] = module
    specification.loader.exec_module(module)
    check_adapter(module)


if __name__ == "__main__":
    main()
