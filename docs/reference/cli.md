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

# CLI reference

```text
osdd2pygeofilter [OPTIONS] OSDD
```

`OSDD` is one local path, HTTP/HTTPS URL, `file://` URL, or OCI URL pointing to an
OpenSearch Description Document. The first application/json results URL in the document is used.

## Options

| Option | Environment variable | Meaning |
| --- | --- | --- |
| `--output PATH` | — | Required destination Python file. Creates parents and replaces existing output. |
| `--oauth2-bearer TEXT` | `OAUTH2_BEARER` | Bearer token for HTTP/HTTPS retrieval. |
| `--oci-hostname TEXT` | `OCI_HOSTNAME` | Registry host for explicit credentials; requires username and password too. |
| `--oci-username TEXT` | `OCI_USERNAME` | Registry username. |
| `--oci-password TEXT` | `OCI_PASSWORD` | Registry password. |
| `--authfile PATH` | `REGISTRY_AUTH_FILE` | Registry credentials file; default described below. |
| `--help` | — | Show usage and exit. |

Explicit options take precedence over the corresponding environment variables.
There is no `--version` option, URL-selection option, or CQL2 evaluation subcommand.

### Default credentials file

On Linux, the default is `$XDG_RUNTIME_DIR/containers/auth.json` when
`XDG_RUNTIME_DIR` is set. Otherwise, including on macOS and Windows, it is
`~/.config/containers/auth.json`. Missing files use empty credentials. When all
three explicit OCI credentials are supplied, they are added to the loaded
credentials for the specified host.

## Output and exit status

Python source is written to the requested file. Operational logs go to stderr.

| Status | Meaning |
| --- | --- |
| `0` | Generation succeeded, or help was displayed. |
| `1` | Reading, parsing, generation, or writing failed. |
| `2` | Command-line usage error, such as a missing required option. |

See [CLI usage](../how-to/use-cli.md) for command examples and
[the walkthrough](../tutorials/first-steps.md) for using the generated file.
