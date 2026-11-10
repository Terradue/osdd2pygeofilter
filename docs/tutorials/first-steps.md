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

# Generate your first evaluator

First [install the CLI](../how-to/install.md). This walkthrough uses a local
description, so no running search service is needed.

## 1. Save a description

Create `opensearch.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>Example search</ShortName>
  <Description>Example search service</Description>
  <Tags>example search</Tags>
  <Url type="application/json"
       template="https://example.test/search?q={searchTerms}&amp;limit={count?}&amp;format=json"/>
</OpenSearchDescription>
```

`searchTerms` is required, `count` is optional, and `format=json` is fixed.
The XML uses `&amp;` to separate query parameters.

## 2. Generate the module

```bash
osdd2pygeofilter opensearch.xml --output search_evaluator.py
```

The command writes `search_evaluator.py`. Choose an output
filename that is a valid Python module name. Existing output is replaced.

## 3. Convert a filter

Save the following as `search_example.py` beside the generated file:

```python
from search_evaluator import from_cql2_text

query = from_cql2_text("searchTerms = 'ocean & ice' AND count = 10")
print(query)
```

Run it in the same Python environment:

```bash
python search_example.py
```

Output:

```text
{'q': 'ocean & ice', 'limit': '10'}
```

CQL2 property names match template placeholders: `searchTerms` maps to `q`, and
`count` maps to `limit`. The dictionary contains decoded filter values.
To validate the complete query and call the service, use the generated helper:

```python
from search_evaluator import invoke

response = invoke(query)
```

This merges defaults with filter values, validates them, expands the original
URL template (preserving fixed values such as `format=json`), and makes an HTTP GET (the default when no method is declared). Parameters with advertised options log a warning during
conversion when their value is not listed; options are suggestions, so this
warning does not prevent the request.

Next, learn about [remote sources and authentication](../how-to/use-cli.md) and
[which queries are supported](../explanation/architecture.md).

For a complete live-service example, continue with
[Search EUMETSAT products with CQL2](eumetsat.md).
