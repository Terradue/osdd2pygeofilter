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

# API reference

`convert(service, target, *, url_index=0)` accepts an
`lxml.etree._Element` root element and a `pathlib.Path`. It validates and
renders the evaluator before creating parent directories and replacing the
output. It returns the target path. `render_evaluator(service, *, url_index=0)`
returns the same Python source without writing it.

```python
from pathlib import Path
from lxml import etree
from osdd2pygeofilter.converter import convert

parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
service = etree.parse("opensearch.xml", parser).getroot()
convert(service, Path("generated_search.py"))
```

Only `Url` elements with `type="application/json"` and a results relation
(including the default relation) are eligible. `url_index` selects among these
URLs in document order. No requests are made during conversion.

## Generated API

The module contains `OpenSearchEvaluator(Evaluator)` and these convenience APIs:

```python
from generated_search import from_cql2_text, from_cql2_json

# For a template https://example.test/search?q={searchTerms}&limit={count?}
query = from_cql2_text("searchTerms = 'ocean & ice' AND count = 10")
assert query == {"q": "ocean & ice", "limit": "10"}
query = from_cql2_json('{"op":"=","args":[{"property":"searchTerms"},"ice"]}')
```

`to_opensearch(root)` accepts an existing pygeofilter AST. Query conversion
functions return decoded filter parameters without making a request. They accept
`attribute_map`, mapping application property names to placeholder QNames.
Each evaluation is independent.

`invoke(parameters, defaults=None)` merges decoded defaults and fixed template
parameters, validates the complete parameter set, and sends an HTTP GET using
`requests` with a 30-second timeout. Filter assignments override defaults; fixed
template values cannot be changed. It raises for HTTP errors and returns the
response's decoded JSON. `invoke_from_cql2_text` and `invoke_from_cql2_json`
combine conversion and invocation:

```python
from generated_search import invoke_from_cql2_text

response = invoke_from_cql2_text(
    "text = 'ice'",
    attribute_map={"text": "searchTerms"},
    defaults={"limit": "10"},
)
```

Quote extension property names in CQL2 text, for example
`"eo:cloudCover" < 20`. Use `attribute_map` to expose names such as `cloud_cover`.
The prefix must match the description's placeholder; its meaning is resolved
using the XML namespace URI, including declarations scoped to a URL.

The generated module requires `pygeofilter`, `pygeoif` (also a dependency
of pygeofilter), and `requests`. It does not import `osdd2pygeofilter`, Jinja2,
or lxml at runtime. The generator embeds the validation definitions from its
canonical validation source alongside the Jinja2-rendered handlers. Validation
fixes take effect in existing modules when you regenerate them.

`PARAMETER_OPTIONS` maps HTTP query parameter names to tuples of suggested
values, for example `{"platform": ("Sentinel-1", "Sentinel-2")}`. Option labels
are omitted. Options alone do not restrict accepted values or imply an enum.

Whenever a handler assigns a parameter value absent from its advertised tuple,
it immediately emits a `WARNING` log record. Listed values, absent
parameters, and parameters without options produce no warning. Comparison uses
the complete decoded value, including any range, set, or sort syntax.
Repeated assignments are checked separately. Computed interval intersections
and spatial relation assignments are also checked; copying already checked
values while merging predicates does not add warnings. Warnings can therefore
be emitted even when a later part of the expression fails. The value remains
unchanged and can be submitted by the invocation helpers.
Patterns and standard-defined enumerations are still validated at invocation.

Warnings use Python's standard `logging` module, under the generated module's
name. Applications can configure handlers and levels normally; the generated
module does not configure logging. Defaults supplied only to `invoke` are not
part of evaluator option checks.


The converter reads namespace scopes, URL offsets and constraint attributes
directly from the lxml tree. Pass the OpenSearchDescription root element, using
`.getroot()` when loading an ElementTree. The CLI parses XML with entity
resolution, DTD loading and network access disabled. Programmatic callers are
responsible for their parser configuration.

See [supported queries and constraints](../explanation/architecture.md) for
translation limits. Unsupported predicates raise `NotImplementedError`; invalid
values, missing required parameters and conflicting assignments raise
`ValueError`.

::: osdd2pygeofilter.converter

## Generated source quality

Generated modules are formatted for the project's 100-column Ruff configuration
and checked with its strict mypy and Bandit settings. Run
`hatch run dev:generated-check` to verify representative outputs, including
empty bindings, empty metadata maps, and escaped option values. This check is
included in the development quality and check commands.

The emitted source has typed parameter metadata and a recursive `JSONValue`
alias for decoded JSON responses (objects, arrays, scalars, or null). The alias
expresses JSON syntax, not a service-specific response schema. Invocation
validates values returned across the HTTP client's untyped JSON boundary.

Pygeofilter 0.4.0 does not ship a `py.typed` marker. The template documents narrow
`import-untyped` exceptions for its imports and a `misc` exception for inheriting
its untyped evaluator. A typed handler-registration adapter preserves method
signatures; evaluator results are checked before exposing parameter dictionaries.
`@_handle` calls the original `handle` decorator to register each function, then
returns that same function with its generic callable type preserved. The leading
underscore marks this as an internal helper; it does not change dispatch behavior.
Using the untyped upstream decorator directly would erase handler signatures
and trigger strict mypy's `untyped-decorator` errors.
No host-wide mypy override is needed. Revisit these dependency exceptions when
upgrading to a pygeofilter release that publishes typing metadata.
