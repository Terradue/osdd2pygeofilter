"""Validate compiled OpenSearch parameter bindings and extension values.

Bindings are internal compiler metadata, not replacements for schema models.
Namespace URIs determine semantics; XML prefixes and HTTP query names do not.
"""

from __future__ import annotations

import codecs
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

CORE = "http://a9.com/-/spec/opensearch/1.1/"
PARAMETERS = "http://a9.com/-/spec/opensearch/extensions/parameters/1.0/"
GEO = "http://a9.com/-/opensearch/extensions/geo/1.0/"
TIME = "http://a9.com/-/opensearch/extensions/time/1.0/"
EO = "http://a9.com/-/opensearch/extensions/eo/1.0/"
SRU = "http://a9.com/-/opensearch/extensions/sru/2.0/"

EO_INTEGERS = frozenset(
    {
        "wavelength",
        "denominator",
        "orbitNumber",
        "cloudCover",
        "snowCover",
        "startTimeFromAscendingNode",
        "completionTimeFromAscendingNode",
    }
)
EO_NUMBERS = frozenset(
    {
        "resolution",
        "distanceValue",
        "lowestLocation",
        "highestLocation",
        "illuminationAzimuthAngle",
        "illuminationZenithAngle",
        "illuminationElevationAngle",
        "minimumIncidenceAngle",
        "maximumIncidenceAngle",
        "dopplerFrequency",
        "incidenceAngleVariation",
    }
)
EO_DATES = frozenset(
    {
        "publicationDate",
        "specificationDate",
        "creationDate",
        "modificationDate",
        "processingDate",
        "availabilityTime",
    }
)
EO_ENUMS = MappingProxyType(
    {
        "orbitDirection": ("ASCENDING", "DESCENDING"),
        "polarisationMode": ("S", "D", "T", "Q", "UNDEFINED"),
        "antennaLookDirection": ("LEFT", "RIGHT"),
        "acquisitionType": ("NOMINAL", "CALIBRATION", "OTHER"),
        "productQualityStatus": ("NOMINAL", "DEGRADED"),
        "hasSecurityConstraints": ("true", "false"),
    }
)


@dataclass(frozen=True)
class Binding:
    """Compiler metadata linking a property, query key, and validation rules.

    Attributes:
        property: Placeholder QName exposed as a CQL2 property.
        query: HTTP query parameter name.
        namespace: Resolved namespace URI of the placeholder.
        local: Local placeholder name.
        required: Whether the template requires a replacement value.
        constraints: Parameter extension annotations, including repeated options.
    """

    property: str
    query: str
    namespace: str
    local: str
    required: bool
    constraints: tuple[tuple[str, str], ...] = ()

    def check_definition(self) -> None:
        """Reject malformed constraints or unsupported occurrence counts.

        Raises:
            ValueError: If declared constraints cannot be enforced.
        """
        for key, value in self.constraints:
            if key in {"minInclusive", "maxInclusive", "minExclusive", "maxExclusive", "step"}:
                number = self.comparable(value)
                if key == "step" and number <= 0:
                    raise ValueError("Parameter step must be positive")
            if key in {"minimum", "maximum"} and value not in {"0", "1"}:
                raise ValueError("Only scalar Parameter occurrence counts 0 and 1 are supported")
            if key == "pattern":
                try:
                    re.compile(value)
                except re.error as error:
                    raise ValueError(f"Invalid parameter pattern: {self.query}") from error

    def validate(self, value: str) -> None:
        """Validate one decoded replacement value.

        Raises:
            ValueError: If a standard or advertised constraint is violated.
        """
        if not value and (self.required or ("minimum", "1") in self.constraints):
            raise ValueError(f"Missing required parameter: {self.property}")
        validators = {CORE: _core, GEO: _geo, TIME: _time, EO: _eo, SRU: _sru}
        validator = validators.get(self.namespace)
        if validator is not None:
            validator(self.local, value)
        parts = [value]
        if self.namespace == EO:
            parts, is_range = _range_parts(value)
            kind = "rangeAllowed" if is_range else "setAllowed"
            if (is_range or value.startswith("{")) and (
                f"{{{EO}}}{kind}",
                "false",
            ) in self.constraints:
                raise ValueError(f"Parameter disallows {kind}")
        for part in parts:
            if part or self.namespace != EO:
                _advertised(part, self)

    def comparable(self, value: str) -> float:
        """Convert a bound to a comparable number or UTC timestamp."""
        if self.namespace == TIME or (self.namespace == EO and self.local in EO_DATES):
            return _date_number(value)
        return _number(value)


def _number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Expected a finite number")
    return number


def _integer(value: str, minimum: int = 0) -> None:
    if not re.fullmatch(r"[+]?\d+", value) or int(value) < minimum:
        raise ValueError(f"Expected an integer >= {minimum}: {value}")


def _choice(value: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise ValueError(f"Expected one of {choices}: {value}")


def _core(local: str, value: str) -> None:
    if local in {"count", "startIndex", "startPage"}:
        _integer(value)
    elif (
        local == "language"
        and value != "*"
        and not re.fullmatch(r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*", value)
    ):
        raise ValueError("Expected a language tag or '*'")


def _time(local: str, value: str) -> None:
    if local in {"start", "end"}:
        timestamp(value)


def timestamp(value: str) -> datetime:
    """Parse an RFC 3339 timestamp, requiring an explicit timezone.

    Raises:
        ValueError: If the timestamp is malformed or has no timezone.
    """
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError(f"Expected an RFC 3339 timestamp: {value}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _box(value: str) -> None:
    coordinates = [_number(item) for item in value.split(",")]
    if len(coordinates) != 4:
        raise ValueError("A box needs west,south,east,north")
    west, south, east, north = coordinates
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("Invalid WGS84 bounding box")


def _geo(local: str, value: str) -> None:
    if local == "box":
        _box(value)
    elif local in {"lat", "lon", "radius"}:
        number = _number(value)
        bounds = {"lat": (-90, 90), "lon": (-180, 180), "radius": (0, math.inf)}
        lower, upper = bounds[local]
        if not lower <= number <= upper:
            raise ValueError(f"Invalid geo:{local}")
    elif local == "relation":
        _choice(value, ("intersects", "contains", "disjoint"))
    elif local == "geometry":
        _geometry(value)


def _geometry(value: str) -> None:
    """Validate WKT using pygeofilter's existing geometry dependency."""
    from pygeoif.exceptions import WKTParserError
    from pygeoif.factories import from_wkt

    try:
        geometry = from_wkt(value)
    except (WKTParserError, ValueError) as error:
        raise ValueError("Invalid WKT geometry") from error
    if geometry is None or geometry.is_empty or geometry.has_z:
        raise ValueError("Expected a valid nonempty 2D geometry")
    _box(",".join(str(item) for item in geometry.bounds))


def _date_number(value: str) -> float:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp()
    return timestamp(value).timestamp()


def _range_parts(value: str) -> tuple[list[str], bool]:
    if value.startswith("{") and value.endswith("}"):
        parts = value[1:-1].split(",")
        if not all(parts):
            raise ValueError("Empty set member")
        return parts, False
    if value[:1] in {"[", "]", "("} and value[-1:] in {"[", "]", ")"}:
        parts = value[1:-1].split(",")
        if len(parts) != 2 or not any(parts):
            raise ValueError("Expected two range bounds")
        return parts, True
    if value[:1] in {"[", "]"}:
        return [value[1:], ""], True
    if value[-1:] in {"[", "]"}:
        return ["", value[:-1]], True
    return [value], False


def _eo_scalar(local: str, value: str) -> float:
    if local in EO_DATES:
        return _date_number(value)
    number = _number(value)
    if local in EO_INTEGERS and not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError(f"Expected integer for eo:{local}")
    if local in {"cloudCover", "snowCover"} and not 0 <= number <= 100:
        raise ValueError(f"eo:{local} must be in [0,100]")
    return number


def _eo(local: str, value: str) -> None:
    if local in EO_ENUMS:
        for part in _range_parts(value)[0]:
            _choice(part, EO_ENUMS[local])
    elif local in EO_INTEGERS | EO_NUMBERS | EO_DATES:
        parts, is_range = _range_parts(value)
        numbers = [_eo_scalar(local, part) for part in parts if part]
        if not numbers or (not is_range and len(numbers) != len(parts)):
            raise ValueError("Empty EO value")
        if is_range and len(numbers) == 2 and numbers[0] > numbers[1]:
            raise ValueError("Reversed EO interval")


def _sru(local: str, value: str) -> None:
    if local in {"startRecord", "facetStart"}:
        _integer(value, 1)
    elif local in {"maximumRecords", "resultSetTTL", "facetLimit"}:
        _integer(value)
    elif local == "recordPacking":
        _choice(value, ("string", "xml"))
    elif local == "rendering":
        _choice(value, ("client", "server"))
    elif local == "sortKeys":
        _sort_keys(value)
    elif local == "facetSort":
        _facet_sort(value)


def _sort_keys(value: str) -> None:
    if not value.strip():
        raise ValueError("Empty SRU sortKeys")
    for key in value.split():
        fields = key.split(",")
        if not fields[0] or len(fields) > 5:
            raise ValueError("Invalid SRU sort key")
        for flag in fields[2:4]:
            _choice(flag, ("", "0", "1", "true", "false"))


def _facet_sort(value: str) -> None:
    parts = value.split(",")
    if len(parts) > 3:
        raise ValueError("Invalid SRU facetSort")
    for part, choices in zip(
        parts,
        (
            ("recordCount", "alphanumeric"),
            ("ascending", "descending"),
            ("caseSensitive", "caseInsensitive"),
        ),
        strict=False,
    ):
        _choice(part, choices)


def _advertised(value: str, binding: Binding) -> None:
    constraints = binding.constraints
    for key, bound in constraints:
        if key == "pattern" and re.fullmatch(bound, value) is None:
            raise ValueError(f"Value does not match parameter pattern: {value}")
        if key in {"minInclusive", "maxInclusive", "minExclusive", "maxExclusive"}:
            _numeric_bound(key, binding.comparable(value), binding.comparable(bound))
        if key == "maximum" and bound == "0":
            raise ValueError("Parameter maximum occurrence is zero")
        if key == "step":
            _step(value, bound, dict(constraints).get("minInclusive", "0"))


def _numeric_bound(kind: str, value: float, bound: float) -> None:
    valid = {
        "minInclusive": value >= bound,
        "maxInclusive": value <= bound,
        "minExclusive": value > bound,
        "maxExclusive": value < bound,
    }
    if not valid[kind]:
        raise ValueError(f"Value violates {kind}={bound}")


def validate_parameters(
    bindings: tuple[Binding, ...],
    values: Mapping[str, str],
    declarations: Mapping[str, tuple[str, ...]],
    offsets: tuple[int, int],
) -> None:
    """Validate all replacements, including related time and pagination bounds.

    Raises:
        ValueError: If required values are absent or constraints are violated.
    """
    semantic: dict[tuple[str, str], str] = {}
    for binding in bindings:
        value = values.get(binding.query)
        required = binding.required or ("minimum", "1") in binding.constraints
        if value is None:
            if required:
                raise ValueError(f"Missing required parameter: {binding.property}")
            continue
        binding.validate(value)
        semantic[binding.namespace, binding.local] = value
        if binding.namespace == CORE:
            _declared_core(binding.local, value, declarations, offsets)
    start, end = semantic.get((TIME, "start")), semantic.get((TIME, "end"))
    if start is not None and end is not None and timestamp(start) > timestamp(end):
        raise ValueError("Time start must not follow time end")


def _declared_core(
    local: str,
    value: str,
    declarations: Mapping[str, tuple[str, ...]],
    offsets: tuple[int, int],
) -> None:
    if local in {"startIndex", "startPage"}:
        _integer(value, offsets[local == "startPage"])
    if local in {"inputEncoding", "outputEncoding"}:
        try:
            encoding = codecs.lookup(value)
        except LookupError as error:
            raise ValueError(f"Unknown character encoding: {value}") from error
        if local == "inputEncoding" and encoding.name != "utf-8":
            raise ValueError("URL expansion supports UTF-8 inputEncoding only")
    advertised = declarations.get(local, ())
    if advertised and "*" not in advertised:
        _choice(value, advertised)


def intersect_ranges(binding: Binding, left: str, right: str) -> str:
    """Intersect EO numeric/date ranges when combining CQL2 predicates.

    Raises:
        ValueError: If assignments conflict or their intersection is empty.
    """
    if binding.namespace != EO or binding.local not in EO_INTEGERS | EO_NUMBERS | EO_DATES:
        raise ValueError(f"Conflicting assignments for {binding.property}")
    binding.validate(left)
    binding.validate(right)
    _left_parts, left_range = _range_parts(left)
    _right_parts, right_range = _range_parts(right)
    if not left_range or not right_range:
        raise ValueError(f"Cannot combine distinct scalar/set assignments for {binding.property}")
    lower, lower_closed = _intersect_bound(binding.local, left, right, 0)
    upper, upper_closed = _intersect_bound(binding.local, left, right, 1)
    if lower and upper:
        difference = _eo_scalar(binding.local, lower) - _eo_scalar(binding.local, upper)
        if difference > 0 or (difference == 0 and not (lower_closed and upper_closed)):
            raise ValueError("Empty EO interval intersection")
    return _format_interval(lower, upper, lower_closed, upper_closed)


def _intersect_bound(local: str, left: str, right: str, index: int) -> tuple[str, bool]:
    left_bound = _range_parts(left)[0][index]
    right_bound = _range_parts(right)[0][index]
    position, closed = (0, "[") if index == 0 else (-1, "]")
    if not left_bound:
        return right_bound, right[position] == closed
    if not right_bound:
        return left_bound, left[position] == closed
    left_number, right_number = _eo_scalar(local, left_bound), _eo_scalar(local, right_bound)
    if left_number == right_number:
        return left_bound, left[position] == right[position] == closed
    choose_left = left_number > right_number if index == 0 else left_number < right_number
    source = left if choose_left else right
    return (left_bound if choose_left else right_bound), source[position] == closed


def _step(value: str, step: str, base: str) -> None:
    quotient = (_number(value) - _number(base)) / _number(step)
    if not math.isclose(quotient, round(quotient)):
        raise ValueError("Value violates parameter step")


def _format_interval(lower: str, upper: str, lower_closed: bool, upper_closed: bool) -> str:
    opening = "[" if lower_closed else "]"
    closing = "]" if upper_closed else "["
    if not lower:
        return upper + closing
    if not upper:
        return opening + lower
    return opening + lower + "," + upper + closing
