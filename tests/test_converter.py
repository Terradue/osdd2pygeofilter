from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape

import pytest
from lxml import etree

from osdd2pygeofilter.converter import convert, render_evaluator
from osdd2pygeofilter.validation import CORE, EO, GEO, PARAMETERS, SRU, TIME

if TYPE_CHECKING:
    from collections.abc import Mapping


class GeneratedModule(Protocol):
    def from_cql2_text(
        self,
        expression: str,
        *,
        attribute_map: Mapping[str, str] | None = None,
        defaults: Mapping[str, str] | None = None,
    ) -> str: ...

    def from_cql2_json(self, expression: str) -> str: ...

    def build_url(self, parameters: Mapping[str, str] | None = None) -> str: ...


def service(
    template: str, children: str = "", attributes: str = "", extra: str = ""
) -> etree._Element:
    xml = f'''<OpenSearchDescription xmlns="{CORE}" xmlns:p="{PARAMETERS}"
        xmlns:earth="{EO}" xmlns:g="{GEO}" xmlns:t="{TIME}" xmlns:s="{SRU}"
        xmlns:eum="https://www.eumetsat.int/opensearch/extensions/0.1/">
        <ShortName>Test</ShortName><Description>Test service</Description><Tags>test</Tags>
        <Url type="application/atom+xml" template="https://wrong.test/?q={{searchTerms}}"/>
        <Url type="application/json" template="{escape(template, {'"': "&quot;"})}" {attributes}>
        {children}</Url>{extra}</OpenSearchDescription>'''
    return etree.fromstring(xml.encode())


def generate(tmp_path: Path, description: etree._Element) -> GeneratedModule:
    target = convert(description, tmp_path / "generated.py")
    specification = importlib.util.spec_from_file_location("generated", target)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    with patch.dict(sys.modules, {"generated": module}):
        specification.loader.exec_module(module)
    return module


@pytest.fixture
def adapter(tmp_path: Path) -> GeneratedModule:
    return generate(
        tmp_path,
        service(
            "https://example.test/search?q={searchTerms?}&n={count?}&start={startIndex?}"
            "&cloud={earth:cloudCover?}&orbit={earth:orbitDirection?}&bbox={g:box?}"
            "&geometry={g:geometry?}&relation={g:relation?}&begin={t:start?}&end={t:end?}"
            "&sort={s:sortKeys?}&packing={s:recordPacking?}&format=json",
        ),
    )


def test_selects_json_and_encodes_once(adapter: GeneratedModule) -> None:
    query = adapter.from_cql2_text("searchTerms = 'ocean & ice+雪%20' AND count = 10")
    assert parse_qs(query) == {"q": ["ocean & ice+雪%20"], "n": ["10"], "format": ["json"]}
    assert adapter.build_url({"q": "a&b"}) == "https://example.test/search?q=a%26b&format=json"


def test_json_reversed_equality_aliases_defaults(adapter: GeneratedModule) -> None:
    assert parse_qs(
        adapter.from_cql2_json('{"op":"=","args":["ocean",{"property":"searchTerms"}]}')
    )["q"] == ["ocean"]
    query = adapter.from_cql2_text(
        "text = 'ice'", attribute_map={"text": "searchTerms"}, defaults={"n": "5"}
    )
    assert parse_qs(query)["n"] == ["5"]


def test_repeated_calls_are_independent(adapter: GeneratedModule) -> None:
    adapter.from_cql2_text("count = 5")
    assert "n" not in parse_qs(adapter.from_cql2_text("searchTerms = 'ice'"))
    assert parse_qs(adapter.from_cql2_text("count = 5 AND count = 5"))["n"] == ["5"]
    with pytest.raises(ValueError, match="Conflicting"):
        adapter.from_cql2_text("count = 5 AND count = 6")


@pytest.mark.parametrize(
    "expression",
    [
        "count = -1",
        "count = 1.5",
        "count = TRUE",
        "startIndex = 0",
        '"earth:cloudCover" = 101',
        "\"earth:cloudCover\" = '[0,101]'",
        "\"earth:cloudCover\" = '[50,20]'",
        "\"earth:orbitDirection\" = 'UP'",
        "\"g:box\" = '0,91,1,92'",
        "\"g:box\" = '0,1,2'",
        "\"g:box\" = 'NaN,0,1,2'",
        "\"g:relation\" = 'near'",
        "\"t:start\" = '2025-02-30T00:00:00Z'",
        "\"t:start\" = '2025-01-01'",
        "\"t:start\" = '2025-01-02T00:00:00Z' AND \"t:end\" = '2025-01-01T00:00:00Z'",
        "\"s:recordPacking\" = 'binary'",
        "\"s:sortKeys\" = 'title,,2'",
    ],
)
def test_standard_constraints(adapter: GeneratedModule, expression: str) -> None:
    with pytest.raises(ValueError):
        adapter.from_cql2_text(expression)


def test_antimeridian_and_offsets(tmp_path: Path, adapter: GeneratedModule) -> None:
    assert parse_qs(adapter.from_cql2_text("\"g:box\" = '170,-20,-170,20'"))["bbox"] == [
        "170,-20,-170,20"
    ]
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?i={startIndex}&p={startPage}",
            attributes='indexOffset="0" pageOffset="0"',
        ),
    )
    assert parse_qs(generated.from_cql2_text("startIndex = 0 AND startPage = 0")) == {
        "i": ["0"],
        "p": ["0"],
    }


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('"earth:cloudCover" < 20', "20["),
        ('20 > "earth:cloudCover"', "20["),
        ('"earth:cloudCover" BETWEEN 10 AND 20', "[10,20]"),
        ('"earth:cloudCover" IN (10,20)', "{10,20}"),
        ('"earth:cloudCover" >= 10 AND "earth:cloudCover" < 20', "[10,20["),
    ],
)
def test_eo_ranges(adapter: GeneratedModule, expression: str, expected: str) -> None:
    assert parse_qs(adapter.from_cql2_text(expression))["cloud"] == [expected]


def test_empty_intersection(adapter: GeneratedModule) -> None:
    with pytest.raises(ValueError, match="Empty"):
        adapter.from_cql2_text('"earth:cloudCover" > 10 AND "earth:cloudCover" <= 10')


def test_spatial_intersection_preserves_geometry(adapter: GeneratedModule) -> None:
    result = parse_qs(adapter.from_cql2_text('S_INTERSECTS("g:geometry", POINT(10 20))'))
    assert result["geometry"] == ["POINT (10.0 20.0)"]
    assert result["relation"] == ["intersects"]


@pytest.mark.parametrize(
    "expression",
    [
        "searchTerms = 'a' OR searchTerms = 'b'",
        "NOT count = 2",
        "count < 2",
        "count IS NULL",
        "count = startIndex",
        "count = 2 + 3",
        'S_INTERSECTS("g:box", POINT(10 20))',
    ],
)
def test_unrepresentable_predicates_fail(adapter: GeneratedModule, expression: str) -> None:
    with pytest.raises(NotImplementedError):
        adapter.from_cql2_text(expression)


def test_required_and_unknown_parameters(tmp_path: Path) -> None:
    generated = generate(tmp_path, service("https://example.test/?q={searchTerms}&n={count?}"))
    with pytest.raises(ValueError, match="required"):
        generated.build_url()
    with pytest.raises(ValueError, match="required"):
        generated.build_url({"q": ""})
    with pytest.raises(ValueError, match="Unknown"):
        generated.build_url({"q": "ice", "other": "1"})


def test_parameter_constraints(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?q={searchTerms?}&n={count?}",
            '<p:Parameter name="q" value="{searchTerms?}" minimum="1" pattern="[a-z]+">'
            '<p:Option value="ice"/><p:Option value="snow"/></p:Parameter>'
            '<p:Parameter name="n" value="{count?}" minInclusive="2" maxExclusive="10" step="2"/>',
        ),
    )
    assert parse_qs(urlsplit(generated.build_url({"q": "ice", "n": "4"})).query)["n"] == ["4"]
    for parameters in ({"n": "4"}, {"q": "ocean"}, {"q": "ice", "n": "3"}, {"q": "ice", "n": "10"}):
        with pytest.raises(ValueError):
            generated.build_url(parameters)


def test_document_languages_encodings(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?lang={language?}&enc={inputEncoding?}",
            extra="<Language>en</Language><Language>it</Language><InputEncoding>UTF-8</InputEncoding>",
        ),
    )
    generated.build_url({"lang": "it", "enc": "UTF-8"})
    with pytest.raises(ValueError):
        generated.build_url({"lang": "fr"})
    with pytest.raises(ValueError):
        generated.build_url({"enc": "ASCII"})


@pytest.mark.parametrize(
    "template",
    [
        "https://example.test/{searchTerms}?n={count}",
        "https://example.test/?q=x{searchTerms}",
        "https://example.test/?q={searchTerms}&q={count}",
        "https://example.test/?q={unknown:name}",
        "https://example.test/?q={searchTerms}#fragment",
    ],
)
def test_bad_templates_do_not_overwrite(tmp_path: Path, template: str) -> None:
    target = tmp_path / "existing.py"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError):
        convert(service(template), target)
    assert target.read_text() == "original"


def test_url_selection_and_determinism() -> None:
    description = service(
        "https://example.test/?q={searchTerms?}",
        extra='<Url type="application/json" template="https://second.test/?q={searchTerms?}"/>',
    )
    assert "https://example.test/" in render_evaluator(description)
    assert "https://second.test/" in render_evaluator(description, url_index=1)
    assert render_evaluator(description) == render_evaluator(description)
    with pytest.raises(ValueError):
        render_evaluator(description, url_index=2)


def test_source_literals_are_escaped(tmp_path: Path) -> None:
    generated = generate(tmp_path, service("https://example.test/?q={searchTerms?}&fixed='quoted'"))
    assert parse_qs(urlsplit(generated.build_url()).query)["fixed"] == ["'quoted'"]
    with pytest.raises(ValueError, match="fixed"):
        generated.build_url({"fixed": "replacement"})


def test_eumetsat_advertised_extension(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?set={eum:elementSetName?}&n={count?}",
            '<p:Parameter name="set" value="{eum:elementSetName}" minimum="0">'
            '<p:Option value="full"/><p:Option value="brief"/></p:Parameter>'
            '<p:Parameter name="n" value="{count}" minimum="0" maxExclusive="501"/>',
        ),
    )
    assert parse_qs(generated.from_cql2_text("\"eum:elementSetName\" = 'brief'"))["set"] == [
        "brief"
    ]
    with pytest.raises(ValueError):
        generated.build_url({"set": "unknown"})
    with pytest.raises(ValueError):
        generated.build_url({"n": "501"})


def test_date_bounds_and_eo_member_patterns(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?start={t:start?}&cloud={earth:cloudCover?}",
            '<p:Parameter name="start" value="{t:start}" minInclusive="2025-01-01T00:00:00Z"/>'
            '<p:Parameter name="cloud" value="{earth:cloudCover}" pattern="[0-9]+" earth:rangeAllowed="true" earth:setAllowed="false"/>',
        ),
    )
    generated.build_url({"start": "2025-01-01T01:00:00+01:00", "cloud": "[10,20]"})
    with pytest.raises(ValueError):
        generated.build_url({"start": "2024-01-01T00:00:00Z"})
    with pytest.raises(ValueError, match="setAllowed"):
        generated.build_url({"cloud": "{10,20}"})


def test_url_local_namespace_scope(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?value={earth:cloudCover}",
            attributes='xmlns:earth="urn:custom"',
        ),
    )
    assert parse_qs(generated.from_cql2_text("\"earth:cloudCover\" = 'custom'"))["value"] == [
        "custom"
    ]


def test_no_json_results_url() -> None:
    description = service("https://example.test/?q={searchTerms}", attributes='rel="self"')
    with pytest.raises(ValueError, match="application/json"):
        render_evaluator(description)


def test_cli_writes_evaluator(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from osdd2pygeofilter.cli import main

    source = tmp_path / "osdd.xml"
    source.write_text(
        f'<OpenSearchDescription xmlns="{CORE}"><ShortName>Test</ShortName>'
        '<Description>Test</Description><Tags>test</Tags><Url type="application/json" '
        'template="https://example.test/?q={searchTerms}"/></OpenSearchDescription>',
        encoding="utf-8",
    )
    target = tmp_path / "nested" / "search.py"
    result = CliRunner().invoke(main, [str(source), "--output", str(target)])
    assert result.exit_code == 0, result.output
    assert "class OpenSearchEvaluator(Evaluator)" in target.read_text()


def test_sru_sort_options_allow_flags(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?sort={s:sortKeys?}",
            '<p:Parameter name="sort" value="{s:sortKeys}">'
            '<p:Option value="publicationDate"/><p:Option value="start,time"/></p:Parameter>',
        ),
    )
    generated.build_url({"sort": "publicationDate,,0 start,time,1"})
    with pytest.raises(ValueError):
        generated.build_url({"sort": "unknown,,0"})


@pytest.mark.parametrize("value", ["[0,20]", "{0,20}", "[20", "20[", "]20", "20]"])
def test_eo_standard_range_syntax(adapter: GeneratedModule, value: str) -> None:
    adapter.build_url({"cloud": value})


def test_lxml_root_without_optional_description_metadata(tmp_path: Path) -> None:
    root = etree.fromstring(
        f'<OpenSearchDescription xmlns="{CORE}"><Url type="application/json" '
        'template="https://example.test/?q={searchTerms}"/></OpenSearchDescription>'.encode()
    )
    generated = generate(tmp_path, root)
    assert parse_qs(generated.from_cql2_text("searchTerms = 'ice'")) == {"q": ["ice"]}


def test_rejects_wrong_xml_root() -> None:
    with pytest.raises(ValueError, match="OpenSearchDescription root"):
        render_evaluator(etree.fromstring(b"<unrelated/>"))


def test_missing_template_raises_value_error() -> None:
    root = etree.fromstring(
        f'<OpenSearchDescription xmlns="{CORE}"><Url type="application/json"/></OpenSearchDescription>'.encode()
    )
    with pytest.raises(ValueError, match="template"):
        render_evaluator(root)


def test_cli_does_not_expand_external_entities(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from osdd2pygeofilter.cli import main

    secret = tmp_path / "secret.txt"
    secret.write_text("private-value", encoding="utf-8")
    source = tmp_path / "external.xml"
    source.write_text(
        f'<!DOCTYPE OpenSearchDescription [<!ENTITY external SYSTEM "{secret.as_uri()}">]>'
        f'<OpenSearchDescription xmlns="{CORE}"><Language>&external;</Language>'
        '<Url type="application/json" template="https://example.test/?q={searchTerms}"/>'
        "</OpenSearchDescription>",
        encoding="utf-8",
    )
    target = tmp_path / "search.py"
    result = CliRunner().invoke(main, [str(source), "--output", str(target)])
    assert result.exit_code == 0, result.output
    assert "private-value" not in target.read_text()


def test_generated_module_runs_without_generator_dependencies(tmp_path: Path) -> None:
    target = convert(
        service(
            "https://example.test/?q={searchTerms?}&n={count?}&cloud={earth:cloudCover?}"
            "&geometry={g:geometry?}&start={t:start?}&packing={s:recordPacking?}"
            "&set={eum:elementSetName?}",
            '<p:Parameter name="n" value="{count}" minInclusive="2" step="2"/>'
            '<p:Parameter name="set" value="{eum:elementSetName}">'
            '<p:Option value="full"/><p:Option value="brief"/></p:Parameter>',
        ),
        tmp_path / "standalone.py",
    )
    runner = Path(__file__).parent / "fixtures" / "check_standalone.py"
    result = subprocess.run(
        [sys.executable, "-I", str(runner), str(target)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
