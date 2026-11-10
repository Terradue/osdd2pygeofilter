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

# OpenSearch to pygeofilter

Generate a Python evaluator from an OpenSearch Description Document (OSDD) with
`osdd2pygeofilter`. The generated module translates supported CQL2 filters into
URL-encoded OpenSearch query strings for that service.

## Generate an evaluator

After [installing the CLI](how-to/install.md), supply a description and an output file:

```bash
osdd2pygeofilter https://api.eumetsat.int/data/search-products/1.0.0/os --output eumetsat_evaluator.py
```

Local XML files work too:

```bash
osdd2pygeofilter ./opensearch.xml --output search_evaluator.py
```

The command creates parent directories and replaces an existing output file.
It generates Python source; your application uses that module to convert filters
and makes any search requests.

## Start here

- [Install](how-to/install.md) the command in a Python environment.
- [Generate your first evaluator](tutorials/first-steps.md) with a reproducible local example.
- [Use the CLI](how-to/use-cli.md) with remote descriptions and authentication.
- [CLI reference](reference/cli.md) lists options, environment variables, and exit codes.
- [Supported queries](explanation/architecture.md) explains conversion limitations.

For programmatic generation and advanced integration, see the
[Python API reference](reference/api.md).
