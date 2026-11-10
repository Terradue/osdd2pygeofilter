from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from unittest.mock import patch
from xml.sax.saxutils import escape

import pytest
from lxml import etree

from osdd2pygeofilter.converter import convert, render_evaluator
from osdd2pygeofilter.validation import CORE, EO, GEO, PARAMETERS, SRU, TIME

if TYPE_CHECKING:
    from collections.abc import Mapping


class GeneratedModule(Protocol):
    """Generated conversion APIs and advertised option metadata."""

    URL_TEMPLATE: str

    PARAMETER_OPTIONS: Mapping[str, tuple[str, ...]]

    def from_cql2_text(
        self,
        expression: str,
        *,
        attribute_map: Mapping[str, str] | None = None,
    ) -> dict[str, str]: ...

    def from_cql2_json(self, expression: str | dict[str, object]) -> dict[str, str]: ...

    def invoke(
        self, result: dict[str, str], defaults: Mapping[str, str] | None = None
    ) -> object: ...

    def invoke_from_cql2_text(
        self,
        expression: str,
        *,
        attribute_map: Mapping[str, str] | None = None,
        defaults: Mapping[str, str] | None = None,
    ) -> object: ...

    def invoke_from_cql2_json(
        self,
        expression: str,
        *,
        attribute_map: Mapping[str, str] | None = None,
        defaults: Mapping[str, str] | None = None,
    ) -> object: ...


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
    with pytest.MonkeyPatch.context() as module_patch:
        module_patch.setitem(sys.modules, "generated", module)
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


def test_selects_json_and_preserves_decoded_values(adapter: GeneratedModule) -> None:
    query = adapter.from_cql2_text("searchTerms = 'ocean & ice+雪%20' AND count = 10")
    assert query == {"q": "ocean & ice+雪%20", "n": "10"}
    assert not hasattr(adapter, "build_url")


def test_json_reversed_equality_and_aliases(adapter: GeneratedModule) -> None:
    assert (
        adapter.from_cql2_json('{"op":"=","args":["ocean",{"property":"searchTerms"}]}')["q"]
        == "ocean"
    )
    query = adapter.from_cql2_text("text = 'ice'", attribute_map={"text": "searchTerms"})
    assert query == {"q": "ice"}


def test_repeated_calls_are_independent(adapter: GeneratedModule) -> None:
    adapter.from_cql2_text("count = 5")
    assert "n" not in adapter.from_cql2_text("searchTerms = 'ice'")
    assert adapter.from_cql2_text("count = 5 AND count = 5")["n"] == "5"
    with pytest.raises(ValueError, match="Conflicting"):
        adapter.invoke_from_cql2_text("count = 5 AND count = 6")


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
        adapter.invoke_from_cql2_text(expression)


def test_antimeridian_and_offsets(tmp_path: Path, adapter: GeneratedModule) -> None:
    assert adapter.from_cql2_text("\"g:box\" = '170,-20,-170,20'")["bbox"] == "170,-20,-170,20"
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?i={startIndex}&p={startPage}",
            attributes='indexOffset="0" pageOffset="0"',
        ),
    )
    assert generated.from_cql2_text("startIndex = 0 AND startPage = 0") == {
        "i": "0",
        "p": "0",
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
    assert adapter.from_cql2_text(expression)["cloud"] == expected


def test_empty_intersection(adapter: GeneratedModule) -> None:
    with pytest.raises(ValueError, match="Empty"):
        adapter.invoke_from_cql2_text('"earth:cloudCover" > 10 AND "earth:cloudCover" <= 10')


def test_spatial_intersection_preserves_geometry(adapter: GeneratedModule) -> None:
    result = adapter.from_cql2_text('S_INTERSECTS("g:geometry", POINT(10 20))')
    assert result["geometry"] == "POINT (10.0 20.0)"
    assert result["relation"] == "intersects"


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
        generated.invoke_from_cql2_text("count = 4")
    with pytest.raises(ValueError, match="required"):
        generated.invoke_from_cql2_text("searchTerms = ''")
    with pytest.raises(ValueError, match="Unknown"):
        generated.invoke_from_cql2_text("searchTerms = 'ice' AND other = 1")


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
    assert generated.from_cql2_text("searchTerms = 'ice' AND count = 4")["n"] == "4"
    assert generated.from_cql2_text("searchTerms = 'ocean'") == {"q": "ocean"}
    for parameters in ({"n": "4"}, {"q": "ICE"}, {"q": "ice", "n": "3"}, {"q": "ice", "n": "10"}):
        with pytest.raises(ValueError):
            generated.invoke_from_cql2_text(
                "count = " + parameters.get("n", "4"), defaults=parameters
            )


def test_document_languages_encodings(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?lang={language?}&enc={inputEncoding?}",
            extra="<Language>en</Language><Language>it</Language><InputEncoding>UTF-8</InputEncoding>",
        ),
    )
    generated.from_cql2_text("language = 'it' AND inputEncoding = 'UTF-8'")
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("language = 'fr'")
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("inputEncoding = 'ASCII'")


@pytest.mark.parametrize(
    "template",
    [
        "https://example.test/?q={searchTerms",
        "https://example.test/?q={}",
        "ftp://example.test/?q={searchTerms}",
        "https://example.test/?q={unknown:name}",
        "https://example.test/?q={{searchTerms}}",
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
    with patch("requests.get") as request:
        request.return_value.json.return_value = {}
        generated.invoke_from_cql2_text("searchTerms = 'ice'")
    request.assert_called_once_with("https://example.test/?q=ice&fixed='quoted'", timeout=30)
    with pytest.raises(ValueError, match="fixed"):
        generated.invoke_from_cql2_text("searchTerms = 'ice'", defaults={"fixed": "replacement"})


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
    assert generated.from_cql2_text("\"eum:elementSetName\" = 'brief'")["set"] == "brief"
    assert generated.from_cql2_text("\"eum:elementSetName\" = 'custom'") == {"set": "custom"}
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("count = 501")


def test_date_bounds_and_eo_member_patterns(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?start={t:start?}&cloud={earth:cloudCover?}",
            '<p:Parameter name="start" value="{t:start}" minInclusive="2025-01-01T00:00:00Z"/>'
            '<p:Parameter name="cloud" value="{earth:cloudCover}" pattern="[0-9]+" earth:rangeAllowed="true" earth:setAllowed="false"/>',
        ),
    )
    generated.from_cql2_text(
        '"t:start" = \'2025-01-01T01:00:00+01:00\' AND "earth:cloudCover" BETWEEN 10 AND 20'
    )
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("\"t:start\" = '2024-01-01T00:00:00Z'")
    with pytest.raises(ValueError, match="setAllowed"):
        generated.invoke_from_cql2_text('"earth:cloudCover" IN (10,20)')


def test_url_local_namespace_scope(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?value={earth:cloudCover}",
            attributes='xmlns:earth="urn:custom"',
        ),
    )
    assert generated.from_cql2_text("\"earth:cloudCover\" = 'custom'")["value"] == "custom"


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
    generated.from_cql2_text("\"s:sortKeys\" = 'publicationDate,,0 start,time,1'")
    assert generated.from_cql2_text("\"s:sortKeys\" = 'unknown,,0'") == {"sort": "unknown,,0"}
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("\"s:sortKeys\" = 'unknown,,2'")


@pytest.mark.parametrize("value", ["[0,20]", "{0,20}", "[20", "20[", "]20", "20]"])
def test_eo_standard_range_syntax(adapter: GeneratedModule, value: str) -> None:
    assert adapter.from_cql2_text(f"\"earth:cloudCover\" = '{value}'")["cloud"] == value


def test_lxml_root_without_optional_description_metadata(tmp_path: Path) -> None:
    root = etree.fromstring(
        f'<OpenSearchDescription xmlns="{CORE}"><Url type="application/json" '
        'template="https://example.test/?q={searchTerms}"/></OpenSearchDescription>'.encode()
    )
    generated = generate(tmp_path, root)
    assert generated.from_cql2_text("searchTerms = 'ice'") == {"q": "ice"}


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


@pytest.mark.parametrize("pattern", ["", ' pattern="Sentinel-[0-9]+"'])
def test_options_are_suggestions_with_value_tuples(
    tmp_path: Path, pattern: str, caplog: pytest.LogCaptureFixture
) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?platform={earth:platform?}",
            f'<p:Parameter name="platform" value="{{earth:platform?}}"{pattern}>'
            '<p:Option value="Sentinel-1" label="Sentinel-1 mission"/>'
            '<p:Option value="Sentinel-2"/></p:Parameter>',
        ),
    )
    assert generated.PARAMETER_OPTIONS == {"platform": ("Sentinel-1", "Sentinel-2")}
    caplog.set_level(logging.WARNING)
    for platform in ("Sentinel-1", "Sentinel-3"):
        assert generated.from_cql2_text(f"\"earth:platform\" = '{platform}'") == {
            "platform": platform
        }
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "platform" in caplog.text and "Sentinel-3" in caplog.text
    assert "Sentinel-1 mission" not in caplog.text
    if pattern:
        with pytest.raises(ValueError, match="pattern"):
            generated.invoke_from_cql2_text("\"earth:platform\" = 'Sentinel-1 mission'")
    else:
        assert generated.from_cql2_text("\"earth:platform\" = 'Other mission'") == {
            "platform": "Other mission"
        }


def test_options_do_not_override_standard_enum(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?orbit={earth:orbitDirection?}",
            '<p:Parameter name="orbit" value="{earth:orbitDirection?}">'
            '<p:Option value="ASCENDING"/><p:Option value="UP"/></p:Parameter>',
        ),
    )
    assert generated.from_cql2_text("\"earth:orbitDirection\" = 'DESCENDING'") == {
        "orbit": "DESCENDING"
    }
    with pytest.raises(ValueError):
        generated.invoke_from_cql2_text("\"earth:orbitDirection\" = 'UP'")


def test_defaults_are_validated_and_filter_values_take_precedence(adapter: GeneratedModule) -> None:
    with patch("requests.get") as request:
        request.return_value.json.return_value = {}
        adapter.invoke_from_cql2_text("count = 4", defaults={"n": "2"})
    assert "n=4" in request.call_args.args[0]
    assert "n=2" not in request.call_args.args[0]
    with pytest.raises(ValueError, match="Unknown"):
        adapter.invoke_from_cql2_text("count = 4", defaults={"other": "1"})
    with pytest.raises(ValueError):
        adapter.invoke_from_cql2_text("searchTerms = 'ice'", defaults={"n": "-1"})


def test_option_warnings_follow_each_assignment(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?platform={earth:platform?}&q={searchTerms?}",
            '<p:Parameter name="platform" value="{earth:platform?}">'
            '<p:Option value="Sentinel-1"/></p:Parameter>',
        ),
    )
    caplog.set_level(logging.WARNING)
    generated.from_cql2_text("searchTerms = 'ice'")
    generated.from_cql2_text("\"earth:platform\" = 'Sentinel-1'")
    assert not caplog.records
    assert generated.from_cql2_text(
        "mission = 'Sentinel-3' AND mission = 'Sentinel-3'",
        attribute_map={"mission": "earth:platform"},
    ) == {"platform": "Sentinel-3"}
    first_warning, repeated_warning = caplog.records
    assert first_warning.getMessage() == repeated_warning.getMessage()
    caplog.clear()
    assert generated.from_cql2_json(
        '{"op":"=","args":[{"property":"earth:platform"},"Sentinel-3"]}'
    ) == {"platform": "Sentinel-3"}
    assert len(caplog.records) == 1
    assert caplog.records[0].name == "generated"
    assert "platform" in caplog.text and "Sentinel-3" in caplog.text


@pytest.mark.parametrize("syntax", ["text", "json"])
def test_invocation_accepts_unlisted_options_and_sends_decoded_parameters(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, syntax: str
) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/search?q={searchTerms?}&n={count?}&format=json",
            '<p:Parameter name="q" value="{searchTerms?}"><p:Option value="ice"/></p:Parameter>',
        ),
    )
    caplog.set_level(logging.WARNING)
    with patch("requests.get") as request:
        request.return_value.json.return_value = {"features": []}
        if syntax == "text":
            result = generated.invoke_from_cql2_text(
                "searchTerms = 'snow & ice'", defaults={"n": "5"}
            )
        else:
            result = generated.invoke_from_cql2_json(
                '{"op":"=","args":[{"property":"searchTerms"},"snow & ice"]}',
                defaults={"n": "5"},
            )
    assert result == {"features": []}
    request.assert_called_once_with(
        "https://example.test/search?q=snow%20%26%20ice&n=5&format=json",
        timeout=30,
    )
    request.return_value.raise_for_status.assert_called_once_with()
    assert len(caplog.records) == 1
    assert "snow & ice" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [None, True, 5, 1.5, "text", [1, "two", None], {"features": [{"id": "one"}]}],
)
def test_invocation_preserves_json_response_types(
    adapter: GeneratedModule, payload: object
) -> None:
    with patch("requests.get") as request:
        request.return_value.json.return_value = payload
        assert adapter.invoke({"q": "ice"}) == payload


def test_json_conversion_accepts_decoded_objects(adapter: GeneratedModule) -> None:
    assert adapter.from_cql2_json({"op": "=", "args": [{"property": "count"}, 4]}) == {"n": "4"}


@pytest.mark.parametrize("payload", [{1: "non-string key"}, {"value": object()}])
def test_invocation_rejects_non_json_response_values(
    adapter: GeneratedModule, payload: object
) -> None:
    with patch("requests.get") as request:
        request.return_value.json.return_value = payload
        with pytest.raises(ValueError, match="JSON"):
            adapter.invoke({"q": "ice"})


def test_generated_option_literals_preserve_non_bmp_unicode(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?q={searchTerms?}",
            '<p:Parameter name="q" value="{searchTerms?}"><p:Option value="🛰️雪"/></p:Parameter>',
        ),
    )
    assert generated.PARAMETER_OPTIONS == {"q": ("🛰️雪",)}
    assert generated.from_cql2_text("searchTerms = '🛰️雪'") == {"q": "🛰️雪"}


@pytest.mark.parametrize(
    ("expression", "warned_values"),
    [
        ("count = 5", ("5",)),
        ("5 = count", ("5",)),
        ('"earth:cloudCover" < 20', ("20[",)),
        ('"earth:cloudCover" BETWEEN 10 AND 20', ("[10,20]",)),
        ('"earth:cloudCover" IN (10,20)', ("{10,20}",)),
        (
            '"earth:cloudCover" >= 10 AND "earth:cloudCover" < 20',
            ("[10", "20[", "[10,20["),
        ),
        ('S_INTERSECTS("g:geometry", POINT(10 20))', ("POINT (10.0 20.0)", "intersects")),
    ],
)
def test_handlers_warn_for_assigned_and_computed_values(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    expression: str,
    warned_values: tuple[str, ...],
) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?n={count?}&cloud={earth:cloudCover?}"
            "&geometry={g:geometry?}&relation={g:relation?}",
            '<p:Parameter name="n" value="{count?}"><p:Option value="1"/></p:Parameter>'
            '<p:Parameter name="cloud" value="{earth:cloudCover?}">'
            '<p:Option value="0"/></p:Parameter>'
            '<p:Parameter name="geometry" value="{g:geometry?}">'
            '<p:Option value="POINT (0 0)"/></p:Parameter>'
            '<p:Parameter name="relation" value="{g:relation?}">'
            '<p:Option value="contains"/></p:Parameter>',
        ),
    )
    caplog.set_level(logging.WARNING)
    generated.from_cql2_text(expression)
    assert len(caplog.records) == len(warned_values)
    for record, value in zip(caplog.records, warned_values, strict=True):
        assert record.levelno == logging.WARNING
        assert f"value {value!r} outside advertised options" in record.getMessage()


def test_assignment_warnings_precede_failed_conjunction(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/?n={count?}",
            '<p:Parameter name="n" value="{count?}"><p:Option value="1"/></p:Parameter>',
        ),
    )
    caplog.set_level(logging.WARNING)
    with pytest.raises(ValueError, match="Conflicting"):
        generated.from_cql2_text("count = 5 AND count = 6")
    first_warning, second_warning = caplog.records
    assert "value '5'" in first_warning.getMessage()
    assert "value '6'" in second_warning.getMessage()


@pytest.mark.parametrize(
    ("template", "parameters", "expected"),
    [
        (
            "https://example.test/feed/{startPage?}",
            {},
            "https://example.test/feed/",
        ),
        (
            "https://example.test/find/{searchTerms}?q={searchTerms}&n={count?}",
            {"q": "ice/snow +雪%20"},
            "https://example.test/find/ice%2Fsnow%20%2B%E9%9B%AA%2520"
            "?q=ice%2Fsnow%20%2B%E9%9B%AA%2520&n=",
        ),
        (
            "https://example.test/search?filter=pre:{searchTerms}:{count?}:post"
            "&flag&fixed=%2f+%20&fixed=second#results",
            {"searchTerms": "a&b", "count": "5"},
            "https://example.test/search?filter=pre:a%26b:5:post"
            "&flag&fixed=%2f+%20&fixed=second#results",
        ),
        (
            "https://example.test/?q={searchTerms}&q={count}&q={searchTerms}",
            {"searchTerms": "ice", "count": "3"},
            "https://example.test/?q=ice&q=3&q=ice",
        ),
        (
            "https://example.test/{earth:platform}/items?cloud={earth:cloudCover?}",
            {"earth:platform": "Sentinel-1", "cloud": "[10,20]"},
            "https://example.test/Sentinel-1/items?cloud=%5B10%2C20%5D",
        ),
        (
            "https://example.test/?{searchTerms}=value#section-{count?}",
            {"searchTerms": "ice snow", "count": "2"},
            "https://example.test/?ice%20snow=value#section-2",
        ),
        (
            "https://{eum:host}/search/{searchTerms}",
            {"eum:host": "example.test", "searchTerms": "ice"},
            "https://example.test/search/ice",
        ),
    ],
)
def test_invocation_expands_original_url_template(
    tmp_path: Path, template: str, parameters: dict[str, str], expected: str
) -> None:
    generated = generate(tmp_path, service(template))
    assert template == generated.URL_TEMPLATE
    with patch("requests.get") as request:
        request.return_value.json.return_value = {}
        generated.invoke(parameters)
    request.assert_called_once_with(expected, timeout=30)


def test_path_parameter_uses_declared_name_and_constraints(tmp_path: Path) -> None:
    generated = generate(
        tmp_path,
        service(
            "https://example.test/catalog/{earth:platform}/search/{searchTerms}",
            '<p:Parameter name="platform" value="{earth:platform}" pattern="Sentinel-[0-9]+"/>',
        ),
    )
    with patch("requests.get") as request:
        request.return_value.json.return_value = {}
        generated.invoke_from_cql2_text(
            "\"earth:platform\" = 'Sentinel-3' AND searchTerms = 'snow & ice'"
        )
    request.assert_called_once_with(
        "https://example.test/catalog/Sentinel-3/search/snow%20%26%20ice", timeout=30
    )
    with patch("requests.get") as request, pytest.raises(ValueError, match="pattern"):
        generated.invoke({"platform": "other", "searchTerms": "ice"})
    request.assert_not_called()


def test_required_occurrence_wins_over_optional_repetition(tmp_path: Path) -> None:
    generated = generate(tmp_path, service("https://example.test/{searchTerms?}?q={searchTerms}"))
    with patch("requests.get") as request, pytest.raises(ValueError, match="required"):
        generated.invoke({})
    request.assert_not_called()


def test_expanded_url_requires_http_scheme(tmp_path: Path) -> None:
    template = "{eum:scheme}://example.test/{searchTerms}"
    generated = generate(tmp_path, service(template))
    assert template == generated.URL_TEMPLATE
    with patch("requests.get") as request:
        request.return_value.json.return_value = {}
        generated.invoke({"eum:scheme": "https", "searchTerms": "ice"})
    request.assert_called_once_with("https://example.test/ice", timeout=30)
    with patch("requests.get") as request, pytest.raises(ValueError, match="HTTP"):
        generated.invoke({"eum:scheme": "ftp", "searchTerms": "ice"})
    request.assert_not_called()
