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

# Use the CLI

Supply one OSDD source and a required destination Python file:

```bash
osdd2pygeofilter OSDD --output FILE.py
```

## Remote descriptions

```bash
osdd2pygeofilter https://api.eumetsat.int/data/search-products/1.0.0/os --output generated/eumetsat_evaluator.py
```

Use an endpoint returning OpenSearch XML. The command fetches and parses the
description, then generates an evaluator from its first `Url` with
`type="application/json"` and a results relation (`rel="results"`, also the
default when omitted).
There is no CLI option to select another URL; the [Python API](../reference/api.md)
provides `url_index` for that purpose.

## Local descriptions

```bash
osdd2pygeofilter ./opensearch.xml --output generated/search_evaluator.py
```

Absolute paths and `file://` URLs are also supported. Quote paths containing
spaces. The destination is a file, not a directory. Missing parent directories
are created and existing output is overwritten.

## HTTP bearer authentication

Provide a bearer token through the environment:

```bash
export OAUTH2_BEARER='your-token'
osdd2pygeofilter https://example.test/opensearch.xml --output search_evaluator.py
```

The equivalent option is `--oauth2-bearer`. It authenticates HTTP and HTTPS
retrieval of the description. The token is not embedded in the generated module;
your application handles authentication for subsequent search requests.

## OCI registry authentication

Set `OSDD_OCI_URL` to your description's `oci://` URL supported by the registry
adapter, then supply a containers authentication file if needed:

```bash
osdd2pygeofilter "$OSDD_OCI_URL" --authfile ./auth.json --output search_evaluator.py
```

Alternatively, supply all three of `OCI_HOSTNAME`, `OCI_USERNAME`, and
`OCI_PASSWORD`. The [CLI reference](../reference/cli.md) describes credential-file
lookup and the corresponding options.

## Use the generated module

The CLI accepts an OSDD and generates Python code. To evaluate a CQL2 filter,
import the resulting module as shown in the
[first evaluator walkthrough](../tutorials/first-steps.md). The module returns
parameter dictionaries. Generated invocation helpers validate them and execute HTTP GET requests.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Command not found | Activate the environment where the package is installed. |
| Missing argument or option | Supply both an OSDD source and `--output FILE.py`. |
| HTTP or XML parsing error | Confirm that the source returns OpenSearch XML and authentication is correct. A login page or search response is not an OSDD. |
| Selected URL must have the results relation | The first JSON results `Url` is used. Select a results URL through the Python API's `url_index`. |
| Unsupported template | Check for path placeholders, composite values, fragments, or duplicate query names. See [limitations](../explanation/architecture.md). |
| Parameter extension binding error | Each Parameter needs name/value attributes matching the URL template. |
| Cannot write output | Check permissions and supply a file path. |

Failures are logged with a traceback and exit status `1`. Successful generation
does not guarantee that every CQL2 expression is supported or every parameter
value is accepted by the remote service.
