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
from generated_search import from_cql2_text, from_cql2_json, build_url

# For a template https://example.test/search?q={searchTerms}&limit={count?}
query = from_cql2_text("searchTerms = 'ocean & ice' AND count = 10")
assert query == "q=ocean%20%26%20ice&limit=10"
query = from_cql2_json('{"op":"=","args":[{"property":"searchTerms"},"ice"]}')
url = build_url({"q": "ocean & ice", "limit": "10"})
```

`to_opensearch(root)` accepts an existing pygeofilter AST. Query conversion
functions return a percent-encoded query string without a leading `?`.
`build_url(parameters)` returns the complete invocation URL. Neither sends a
request. All supplied parameter values are decoded strings; do not encode them
before calling these APIs.

Conversion functions and the evaluator constructor accept `attribute_map`,
which maps application property names to placeholder QNames, and `defaults`,
which maps HTTP query names to decoded values. Filter assignments override
defaults; fixed template values cannot be changed. Defaults undergo the same
validation as filter values. Each evaluation is independent.

```python
query = from_cql2_text(
    "text = 'ice'",
    attribute_map={"text": "searchTerms"},
    defaults={"limit": "10"},
)
```

Quote extension property names in CQL2 text, for example
`"eo:cloudCover" < 20`. Use `attribute_map` to expose names such as `cloud_cover`.
The prefix must match the description's placeholder; its meaning is resolved
using the XML namespace URI, including declarations scoped to a URL.

The generated module requires only `pygeofilter`, `pygeoif` (also a dependency
of pygeofilter), and `uritemplate`. It does not import `osdd2pygeofilter`, Jinja2,
or lxml at runtime. The generator embeds the validation definitions from its
canonical validation source alongside the Jinja2-rendered handlers. Validation
fixes take effect in existing modules when you regenerate them. OpenSearch QNames and optional markers are
normalized before RFC 6570 processing; `uritemplate` expands URL query values,
including fixed parameters, exactly once.

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
