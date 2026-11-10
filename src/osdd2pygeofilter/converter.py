"""Compile an lxml OpenSearch description into a service-specific evaluator.

Only JSON results URLs are eligible. Compilation does not contact the service.
"""

from __future__ import annotations

import ast
import json
import re
from functools import partial
from importlib.resources import files
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

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
    return candidates[index]


def _http_method(element: _Element) -> str:
    """Read the declared HTTP method, defaulting to GET.

    Raises:
        ValueError: If the method is not a valid HTTP token.
    """
    method = element.get("method", element.get(f"{{{PARAMETERS}}}method", "GET")).upper()
    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Z-]+", method):
        raise ValueError("Invalid HTTP method")
    return method


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


def _template_tokens(template: str) -> tuple[str, dict[str, str]]:
    """Mask placeholders only for URL inspection, retaining their exact spelling."""
    tokens: dict[str, str] = {}

    def mask(match: re.Match[str]) -> str:
        marker = f"OSDDPLACEHOLDER{len(tokens)}TOKEN"
        while marker in template:
            marker += "X"
        tokens[marker] = match[0]
        return marker

    masked = re.sub(r"\{[^{}]*\}", mask, template)
    if "{" in masked or "}" in masked:
        raise ValueError("Malformed URL template placeholder")
    return masked, tokens


def _query_metadata(query: str, tokens: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Infer unambiguous whole-value query aliases and retain fixed-value guards."""
    pairs = parse_qsl(query, keep_blank_values=True)
    aliases: dict[str, str] = {}
    fixed: dict[str, str] = {}
    for name, value in pairs:
        if not name or any(marker in name for marker in tokens):
            continue
        if value in tokens and sum(key == name for key, _ in pairs) == 1:
            property_name = tokens[value][1:-1].removesuffix("?")
            aliases.setdefault(property_name, name)
        elif not any(marker in value for marker in tokens):
            fixed.setdefault(name, value)
    return aliases, fixed


def _template_binding(token: str, aliases: dict[str, str], element: _Element) -> Binding:
    property_name = token[1:-1].removesuffix("?")
    declarations = [
        parameter.get("name", "")
        for parameter in element.findall(f"{{{PARAMETERS}}}Parameter")
        if parameter.get("value", "").replace("?}", "}") == token.replace("?}", "}")
    ]
    if len(declarations) > 1:
        raise ValueError(f"Ambiguous Parameter declarations for {property_name}")
    query = declarations[0] if declarations else aliases.get(property_name, property_name)
    if not query:
        raise ValueError("Parameter names must not be empty")
    return _binding(query, token, element)


def _compile_url(element: _Element) -> tuple[str, tuple[Binding, ...], dict[str, str]]:
    """Compile parameter metadata while preserving the input template verbatim."""
    template = element.get("template", "")
    masked, tokens = _template_tokens(template)
    parsed = urlsplit(masked)
    dynamic_scheme = any(marker.lower() in parsed.scheme for marker in tokens)
    if (parsed.scheme not in {"http", "https"} and not dynamic_scheme) or not parsed.netloc:
        raise ValueError("Expected an absolute HTTP(S) URL template")
    aliases, fixed = _query_metadata(parsed.query, tokens)
    bindings: dict[str, Binding] = {}
    for token in tokens.values():
        binding = _template_binding(token, aliases, element)
        previous = bindings.get(binding.property)
        if previous is None or binding.required:
            bindings[binding.property] = binding
    _validate_bindings(tuple(bindings.values()), element)
    names = [binding.query for binding in bindings.values()]
    if len(set(names)) != len(names) or set(names) & fixed.keys():
        raise ValueError("Ambiguous template parameter names")
    return template, tuple(bindings.values()), fixed


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
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef)):
            start = node.lineno
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.decorator_list:
                start = node.decorator_list[0].lineno
            return "".join(lines[start - 1 :]).rstrip()
    raise ValueError("Validation source has no definitions")


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
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["python"] = partial(json.dumps, ensure_ascii=False)
    return environment.get_template("evaluator.py.j2").render(
        validation_source=_validation_source(),
        uri=uri,
        method=_http_method(element),
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
    module embeds its validators and requires pygeofilter, pygeoif, requests,
    and uritemplate at runtime, without importing osdd2pygeofilter.

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
