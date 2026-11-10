<!--
Copyright 2026 Terradue

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Supported queries and validation

The generator compiles a JSON results URL from an lxml OpenSearchDescription root element.
Jinja2 emits a pygeofilter evaluator with embedded validation definitions;
`invoke` sends decoded parameters through `requests`. The generated module runs without the
`osdd2pygeofilter` package, Jinja2, or lxml. Regenerate it to pick up changes
to validation rules.
Only advertised placeholders are exposed as properties. Query names may differ
from those properties: `q={searchTerms}` maps `searchTerms` to `q`.

## CQL2 translation

| Expression | Translation |
| --- | --- |
| Scalar equality, including reversed operands | Parameter assignment |
| `AND` | Combine assignments; reject conflicts |
| EO numeric/date `<`, `<=`, `>`, `>=` | EO one-sided interval notation |
| EO numeric/date `BETWEEN` / `IN` | Inclusive interval / set notation |
| Conjunction of EO intervals | Intersect bounds; reject an empty intersection |
| `S_INTERSECTS` on a `geo:geometry` property | Exact WKT and `geo:relation=intersects` when advertised |

Dates and timestamps use ISO serialization; booleans use `true` or `false`.
Identical assignments are deduplicated. Spatial predicates never approximate a
geometry by its bounding box. A bounding box can be assigned directly to the
advertised `geo:box` property.

OpenSearch descriptions do not define a universal translation for arbitrary
CQL2. `OR`, `NOT`, null predicates, arithmetic, functions, general temporal
predicates, and comparisons on parameters without an EO range contract fail
explicitly. Time filters can assign RFC 3339 values to `time:start` and
`time:end`; these are overlap search bounds, not a general implementation of
CQL2 temporal relations. Distinct scalar/set assignments to the same parameter
are rejected, including mixed scalar/interval conjunctions.

## Validation

Invocation validates the complete parameter set, including defaults and fixed values, before sending a request. Evaluation logs warnings for unlisted option values.

| Contract | Checks |
| --- | --- |
| OpenSearch 1.1 | Required placeholders, integer pagination, URL offsets, declared languages and encodings |
| Parameter extension | Required occurrence, scalar occurrence limits, patterns, inclusive/exclusive numeric or date bounds, numeric steps |
| Geo | WGS84 coordinate limits, ordered latitude bounds, antimeridian boxes, finite coordinates/radius, supported relation values, nonempty 2D WKT syntax and bounds |
| Time | RFC 3339 timestamps with timezone, calendar validity, chronological start/end order |
| EO | Numeric/date scalar, set and interval syntax, integer fields, cloud/snow percentages, specified enumerations, advertised range/set restrictions and member patterns |
| SRU | Integer counts/offsets, record packing, rendering, sort-key flags and facet-sort structure |
| EUMETSAT/custom namespaces | QName mapping and constraints advertised by the service's Parameter elements |

WKT checking is syntactic and dimensional; it does not perform GEOS topology
validation. String parameters without standard enums or advertised constraints
remain unrestricted. Unknown extension namespaces do not inherit another
extension's semantics merely because their prefix or local name matches.

The adapter accepts UTF-8 input encoding declarations. Required placeholders need nonempty values.
Optional placeholders are omitted when absent. No service defaults are invented.

Only GET templates with whole query-value placeholders are supported. Composite
or path placeholders, fragments, duplicate query names, unsupported occurrence
counts, and invalid parameter bindings fail during generation. Multiple JSON
results URLs can be selected using `url_index`. Unknown foreign annotations are
retained as metadata but do not trigger network requests or dynamic code.

## Advertised options

Parameter `Option` elements suggest values; they do not establish an exhaustive
enumeration. The generator preserves their submitted values as tuples
in `PARAMETER_OPTIONS`, keyed by HTTP parameter name, and omits labels, without changing the underlying parameter type.
Evaluation logs a `WARNING` for each final value missing from its advertised
options tuple, without rejecting or changing it. Listed values and absent
parameters are silent. A `pattern` alongside options is enforced at invocation,
even for an advertised value. Unlisted values remain valid when they satisfy
the parameter's other constraints.

This follows the [OGC EO guidance](https://docs.ogc.org/is/13-026r9/13-026r9.html)
on supplying patterns when options describe only a subset of possible values.
Closed enumerations require an explicit exhaustive contract; existing
standard-defined enumerations, such as orbit direction, remain enforced.
The generator does not infer a service-specific Enum, Literal, or schema enum
from options alone.

## Specification sources

- [OpenSearch 1.1 Draft 5](https://github.com/dewitt/opensearch/blob/master/mediawiki/Specifications/OpenSearch/1.1/Draft%205.wiki)
- [OGC EO extension 13-026r9](https://docs.ogc.org/is/13-026r9/13-026r9.html)
- [OGC Geo and Time extensions 10-032r8](https://docs.ogc.org/is/10-032r8/10-032r8.pdf)
- [OpenSearch SRU extension](https://github.com/dewitt/opensearch/blob/master/mediawiki/Community/Proposal/Specifications/OpenSearch/Extensions/SRU/1.0/Draft%201.wiki)
- [EUMETSAT live description](https://api.eumetsat.int/data/search-products/1.0.0/os)

The historical EUMETSAT namespace page could not be recovered from the archive:
the exact-URL availability query returned no snapshot, and broader archive
queries returned a temporary outage. Accordingly, EUMETSAT-specific rules are
read from advertised constraints rather than claimed as a complete historical
profile implementation. The live description advertises `eum:elementSetName`
values `full` and `brief`, which are covered by regression tests.
