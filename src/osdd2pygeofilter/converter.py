"""Compile an lxml OpenSearch description into a service-specific evaluator.

Only JSON results URLs are eligible. Compilation does not contact the service.
"""

from __future__ import annotations

import ast
import re
from importlib.resources import files
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from uritemplate import URITemplate

from osdd2pygeofilter.validation import CORE, PARAMETERS, Binding

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from lxml.etree import _Element


def _select_url(root: _Element, index: int) -> _Element:
    candidates = [
        element
        for element in root.findall(f"{{{CORE}}}Url")
        if element.get("type") == "application/json"
        and "results" in element.get("rel", "results").split()
    ]
    if index < 0 or index >= len(candidates):
        raise ValueError("No application/json results URL at the requested url_index")
    selected = candidates[index]
    if selected.get("method", "GET").upper() != "GET":
        raise ValueError("Only GET URL templates are supported")
    return selected


def _qualified_name(name: str, element: _Element) -> tuple[str, str]:
    if ":" not in name:
        return CORE, name
    prefix, local = name.split(":", 1)
    namespace = element.nsmap.get(prefix)
    if namespace is None:
        raise ValueError(f"Undeclared placeholder prefix: {prefix}")
    return namespace, local


def _xml_text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _constraints(element: _Element, query: str, token: str) -> tuple[tuple[str, str], ...]:
    matches = [
        item for item in element.findall(f"{{{PARAMETERS}}}Parameter") if item.get("name") == query
    ]
    if len(matches) > 1:
        raise ValueError(f"Duplicate Parameter definition: {query}")
    if not matches:
        return ()
    parameter = matches[0]
    if parameter.get("value", "").replace("?}", "}") != token.replace("?}", "}"):
        raise ValueError(f"Parameter binding disagrees with template: {query}")
    constraints = [
        (_xml_text(key), _xml_text(value))
        for key, value in parameter.attrib.items()
        if key not in {"name", "value"}
    ]
    constraints.extend(
        ("option", option.get("value", ""))
        for option in parameter.findall(f"{{{PARAMETERS}}}Option")
    )
    return tuple(constraints)


def _binding(query: str, token: str, element: _Element) -> Binding:
    match = re.fullmatch(r"\{([\w.-]+(?::[\w.-]+)?)(\?)?\}", token)
    if match is None:
        raise ValueError(f"Expected a single OpenSearch placeholder for {query}: {token}")
    property_name = match[1]
    namespace, local = _qualified_name(property_name, element)
    binding = Binding(
        property_name,
        query,
        namespace,
        local,
        match[2] is None,
        _constraints(element, query, token),
    )
    binding.check_definition()
    return binding


def _compile_url(element: _Element) -> tuple[str, tuple[Binding, ...], dict[str, str]]:
    template = element.get("template", "")
    # OpenSearch QNames and '?' modifiers are not RFC 6570 variable syntax.
    # Normalize placeholders before letting uritemplate parse/expand the URL.
    normalized = re.sub(r"\{[^{}]*\}", "{value}", template)
    parsed = urlsplit(URITemplate(normalized).uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.fragment:
        raise ValueError("Expected an absolute HTTP(S) template without a fragment")
    if "{" in parsed.path or "{" in parsed.netloc:
        raise ValueError("Only query string placeholders are supported")
    query_text = template.split("?", 1)[1] if "?" in template else ""
    bindings: list[Binding] = []
    fixed: dict[str, str] = {}
    seen: set[str] = set()
    for query, value in parse_qsl(query_text, keep_blank_values=True):
        if not query or query in seen or "{" in query:
            raise ValueError(f"Invalid or duplicate query parameter: {query}")
        seen.add(query)
        if "{" in value or "}" in value:
            bindings.append(_binding(query, value, element))
        else:
            fixed[query] = value
    _validate_bindings(bindings, element)
    names = [binding.query for binding in bindings] + list(fixed)
    # RFC 6570 variable names encode punctuation in arbitrary query names.
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name) for name in names):
        raise ValueError("Query names must be RFC 6570 simple variable names")
    # uri = parsed._replace(query="").geturl() + ("{?" + ",".join(names) + "}" if names else "")
    # URITemplate(uri)
    uri = parsed._replace(query="").geturl()
    return uri, tuple(bindings), fixed


def _validate_bindings(bindings: Sequence[Binding], element: _Element) -> None:
    names = [(binding.namespace, binding.local) for binding in bindings]
    if len(set(names)) != len(names):
        raise ValueError("A placeholder must map to exactly one query parameter")
    for attribute in ("indexOffset", "pageOffset"):
        if int(element.get(attribute, "1")) < 0:
            raise ValueError(f"{attribute} must be non-negative")


def _validation_source() -> str:
    """Embed validation definitions from the same source used by the compiler.

    Only trusted package source is inspected. Preserve its formatting and
    decorators, omitting module imports supplied by the evaluator template.
    Generated modules never read or import this package at runtime.
    """
    source = files("osdd2pygeofilter").joinpath("validation.py").read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    definitions: list[str] = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef)):
            continue
        start = node.lineno
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.decorator_list:
            start = node.decorator_list[0].lineno
        definitions.append("".join(lines[start - 1 : node.end_lineno]).rstrip())
    return "\n\n\n".join(definitions)


def render_evaluator(service: _Element, *, url_index: int = 0) -> str:
    """Render Python source for a JSON results endpoint without writing files.

    Args:
        service: Parsed lxml OpenSearchDescription root element.
        url_index: Zero-based index among application/json results URLs.

    Raises:
        ValueError: If the URL or its parameter declarations cannot be compiled.
    """
    root = service
    if root.tag != f"{{{CORE}}}OpenSearchDescription":
        raise ValueError("Expected an OpenSearch 1.1 OpenSearchDescription root")
    element = _select_url(root, url_index)
    uri, bindings, fixed = _compile_url(element)
    declarations = {
        name: tuple(item.text or "" for item in root.findall(f"{{{CORE}}}{tag}"))
        for name, tag in (
            ("language", "Language"),
            ("inputEncoding", "InputEncoding"),
            ("outputEncoding", "OutputEncoding"),
        )
    }
    environment = Environment(
        loader=PackageLoader("osdd2pygeofilter", "templates"),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    environment.filters["python"] = repr
    return environment.get_template("evaluator.py.j2").render(
        validation_source=_validation_source(),
        uri=uri,
        bindings=bindings,
        fixed=fixed,
        parameter_options={
            parameter.get("name"): tuple(
                option.get("value", "") for option in parameter.findall(f"{{{PARAMETERS}}}Option")
            )
            for parameter in element.findall(f"{{{PARAMETERS}}}Parameter")
            if parameter.find(f"{{{PARAMETERS}}}Option") is not None
        },
        declarations=declarations,
        index_offset=int(element.get("indexOffset", "1")),
        page_offset=int(element.get("pageOffset", "1")),
    )


def convert(service: _Element, target: Path, *, url_index: int = 0) -> Path:
    """Write a generated evaluator, creating parents and replacing the target.

    Validation and rendering finish before the target is opened. The generated
    module embeds its validators and requires pygeofilter, pygeoif, and requests
    at runtime, without importing osdd2pygeofilter.

    Args:
        service: Parsed lxml OpenSearchDescription root element.
        target: Python module to create or replace.
        url_index: Zero-based index among application/json results URLs.

    Returns:
        The target path.

    Raises:
        ValueError: If the selected description cannot be compiled.
        OSError: If the destination cannot be written.
    """
    source = render_evaluator(service, url_index=url_index)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target
