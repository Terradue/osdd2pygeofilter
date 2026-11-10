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

# Install

Use Python 3.11 or newer. From a local checkout of this repository, create a
virtual environment and install the package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
osdd2pygeofilter --help
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell.
For development, use `python -m pip install -e .` instead.

Installation supplies the command and its runtime dependencies, including Jinja2
and pygeofilter. If the command is not found, activate the environment where you
installed the package.

Continue with [your first evaluator](../tutorials/first-steps.md) or
[CLI usage](use-cli.md).
