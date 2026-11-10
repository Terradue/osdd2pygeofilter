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

# Search EUMETSAT products with CQL2

This walkthrough starts with the live [EUMETSAT OpenSearch description](https://api.eumetsat.int/data/search-products/1.0.0/os)
and builds a small catalogue-search application. You will generate an evaluator,
express the same search in CQL2 text and JSON, call the service through both
invocation helpers, and export product identifiers, sensing intervals, and
links to CSV.

The example searches the `EO:EUM:DAT:MSG:HRSEVIRI` collection for Meteosat
SEVIRI products covering an area around Italy during the first hour of
1 January 2024 UTC, ordered by sensing start, newest first. The bounding box
selects overlapping products; it does not crop the satellite data.

The description and response structure were checked against the live service
on 10 November 2026. Catalogue contents and availability can change, so the
examples do not depend on a fixed number of results.

## 1. Generate the evaluator

[Install osdd2pygeofilter](../how-to/install.md), activate that environment,
and run these commands in a working directory:

```bash
osdd2pygeofilter \
  https://api.eumetsat.int/data/search-products/1.0.0/os \
  --output eumetsat_evaluator.py
```

The CLI retrieves the description and selects its JSON results template. That
template includes the fixed `format=json` parameter; you do not need to add it
to the filter. Generation retrieves metadata only, not products.

For a reproducible copy of the description, you can instead save it first:

```bash
curl --fail --location \
  https://api.eumetsat.int/data/search-products/1.0.0/os \
  --output eumetsat-osdd.xml
osdd2pygeofilter eumetsat-osdd.xml --output eumetsat_evaluator.py
```

Keep the generated file beside the application below and use the same Python
environment to run it. Regenerate when you want to pick up changes to the
service description.

## 2. Understand the service parameters

CQL2 property names use the description's placeholder names. The generated
parameter dictionary and `defaults` use the corresponding HTTP parameter names:

| CQL2 property | Parameter key | Purpose in this search |
| --- | --- | --- |
| `eo:parentIdentifier` | `pi` | Required collection identifier |
| `time:start` | `dtstart` | Beginning of the search time window |
| `time:end` | `dtend` | End of the search time window |
| `geo:box` | `bbox` | West, south, east, north in longitude/latitude degrees |
| `sru:sortKeys` | `sort` | `start,time,0` requests descending sensing-start order |
| `eum:elementSetName` | `set` | `full` requests the full metadata element set |
| `count` | `c` | Maximum number of records in this response |

The equalities below assign **OpenSearch search parameters**. For example,
`"time:start" = '2024-01-01T00:00:00Z'` sets the beginning of the requested time
window; it does not require every product to start at exactly midnight. The
service applies the temporal and spatial search semantics.

Use the actual namespace prefixes from this description, and double-quote
names containing a colon in CQL2 text. Keep values decoded: the generated
invocation helper handles URL escaping.

## 3. Write equivalent text and JSON filters

Save this JSON document as `italy-query.json`:

```json
{
  "op": "and",
  "args": [
    {"op": "=", "args": [{"property": "eo:parentIdentifier"}, "EO:EUM:DAT:MSG:HRSEVIRI"]},
    {"op": "=", "args": [{"property": "time:start"}, "2024-01-01T00:00:00Z"]},
    {"op": "=", "args": [{"property": "time:end"}, "2024-01-01T01:00:00Z"]},
    {"op": "=", "args": [{"property": "geo:box"}, "5,35,20,48"]},
    {"op": "=", "args": [{"property": "sru:sortKeys"}, "start,time,0"]},
    {"op": "=", "args": [{"property": "eum:elementSetName"}, "full"]}
  ]
}
```

Create `search_eumetsat.py`, starting with the following code. Append the Python
blocks in the next two sections to the same file.

```python
import csv
import json
from pathlib import Path

from eumetsat_evaluator import (
    from_cql2_json,
    from_cql2_text,
    invoke_from_cql2_json,
    invoke_from_cql2_text,
)

query_text = (
    '"eo:parentIdentifier" = \'EO:EUM:DAT:MSG:HRSEVIRI\''
    ' AND "time:start" = \'2024-01-01T00:00:00Z\''
    ' AND "time:end" = \'2024-01-01T01:00:00Z\''
    ' AND "geo:box" = \'5,35,20,48\''
    ' AND "sru:sortKeys" = \'start,time,0\''
    ' AND "eum:elementSetName" = \'full\''
)
query_json = Path("italy-query.json").read_text(encoding="utf-8")
defaults = {"c": "5"}

text_parameters = from_cql2_text(query_text)
json_parameters = from_cql2_json(query_json)
if text_parameters != json_parameters:
    raise ValueError("The text and JSON filters must describe the same search")
print(text_parameters)
```

Adjacent Python string literals produce one line of CQL2, with spaces before
`AND`. The JSON helper accepts a serialized JSON string as above, or a dictionary.
Neither `from_cql2_*` function makes an HTTP request. Both produce:

```text
{'pi': 'EO:EUM:DAT:MSG:HRSEVIRI', 'dtstart': '2024-01-01T00:00:00Z', 'dtend': '2024-01-01T01:00:00Z', 'bbox': '5,35,20,48', 'sort': 'start,time,0', 'set': 'full'}
```

You may see a warning for `start,time,0`: the description lists `start,time`
as a suggested value, while its option label explicitly explains the descending
form. Options are not a closed enum, so the warning does not prevent the search.
Collection identifiers are also advertised as suggestions in
`PARAMETER_OPTIONS["pi"]` in the generated module.

## 4. Invoke the service using each representation

Append:

```python
response_text = invoke_from_cql2_text(query_text, defaults=defaults)
response_json = invoke_from_cql2_json(query_json, defaults=defaults)

Path("eumetsat-text-results.json").write_text(
    json.dumps(response_text, ensure_ascii=False, indent=2), encoding="utf-8"
)
Path("eumetsat-json-results.json").write_text(
    json.dumps(response_json, ensure_ascii=False, indent=2), encoding="utf-8"
)
```

Each invocation converts its filter, merges defaults, validates the complete
parameter set, expands the original URL template, and performs an HTTP request
with a 30-second timeout. This example deliberately makes **two searches** to
demonstrate both entry points; applications normally choose one representation.
Filter assignments override defaults. The `c` default limits the response to
five records; the current description permits values up to 500.

The return value is decoded JSON, not a `requests.Response`, so do not call
`.json()` on it. The service returns a `FeatureCollection` with top-level
`totalResults` and `features`. These are separate live responses: metadata such
as the update time can differ even when their filters are equivalent.

The generated functions raise `ValueError` for invalid parameters and propagate
HTTP and connection errors from Requests. No product downloads occur here.

## 5. Extract and export the returned products

Append this final block. It checks the response shape, extracts identifiers and
sensing intervals, orders the returned rows chronologically, and writes a CSV
containing the advertised product links:

```python
if not isinstance(response_text, dict) or response_text.get("type") != "FeatureCollection":
    raise ValueError("Expected an EUMETSAT FeatureCollection")
features = response_text.get("features")
if not isinstance(features, list):
    raise ValueError("Expected a features array")

rows: list[tuple[str, str, str]] = []
for feature in features:
    if not isinstance(feature, dict):
        raise ValueError("Expected a product object")
    identifier = feature.get("id")
    properties = feature.get("properties")
    if not isinstance(identifier, str) or not isinstance(properties, dict):
        raise ValueError("Expected a product identifier and properties")
    interval = properties.get("date")
    if not isinstance(interval, str):
        raise ValueError("Expected a sensing interval")

    links = properties.get("links")
    data_links = links.get("data", []) if isinstance(links, dict) else []
    download_url = ""
    if isinstance(data_links, list):
        for link in data_links:
            if isinstance(link, dict):
                href = link.get("href")
                if isinstance(href, str):
                    download_url = href
                    break
    rows.append((identifier, interval, download_url))

rows.sort(key=lambda row: row[1])
with Path("eumetsat-products.csv").open("w", encoding="utf-8", newline="") as output:
    writer = csv.writer(output)
    writer.writerow(("product_id", "sensing_interval", "download_url"))
    writer.writerows(rows)

print(f"Matched: {response_text.get('totalResults')}; returned: {len(features)}")
for identifier, interval, _download_url in rows:
    print(f"{interval}: {identifier}")
print("Saved eumetsat-products.csv")
```

Run the completed application from the directory containing all three files:

```bash
python search_eumetsat.py
```

`properties.date` contains a `start/end` sensing interval, rather than a single
timestamp. Product download links are under `properties.links.data`, not a
STAC `assets` object. The CSV leaves the link empty if none is advertised.
It only records links; downloading products is a separate workflow that may
require EUMETSAT authorization.

This exports **one response page**, not necessarily the entire matching
catalogue. `totalResults` describes all matches, while `len(features)` describes
this page. An empty result still produces a CSV header and saves both JSON
responses. To adapt the search, change the collection, time window, or bounding
box in both representations and keep the parameter-equivalence check.

For supported spatial predicates and other conversion rules, see
[Supported queries](../explanation/architecture.md). For invocation signatures
and encoding behavior, see the [Python API](../reference/api.md).
