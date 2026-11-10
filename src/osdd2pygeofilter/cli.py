# Copyright 2026 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load OpenSearch descriptions and generate CQL2 evaluator modules."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import click
import requests
from loguru import logger
from lxml import etree
from requests.adapters import BaseAdapter, HTTPAdapter
from session_adapters.bearer_auth_http_adapter import BearerAuthHTTPAdapter
from session_adapters.conainers_auth import ContainersAuth
from session_adapters.file_adapter import FileAdapter
from session_adapters.oci_adapter import OCIAdapter

from osdd2pygeofilter.converter import convert


def _default_authfile() -> Path:
    """Resolve the platform default registry credentials path at invocation time."""
    # Windows / macOS
    base_dir = Path.home() / ".config"

    if sys.platform == "linux":
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            base_dir = Path(runtime_dir)

    return base_dir / "containers" / "auth.json"


@click.command()
@click.version_option()
@click.argument("osdd", required=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Destination Python module; parent directories are created.",
)
@click.option("--oci-hostname", envvar="OCI_HOSTNAME", show_envvar=True)
@click.option("--oci-username", envvar="OCI_USERNAME", show_envvar=True)
@click.option("--oci-password", envvar="OCI_PASSWORD", show_envvar=True)
@click.option(
    "--authfile",
    help="Path of the managed registry credentials file",
    envvar="REGISTRY_AUTH_FILE",
    show_envvar=True,
    default=_default_authfile,
    show_default=True,
    required=False,
    type=click.Path(path_type=Path),
)
@click.option("--oauth2-bearer", envvar="OAUTH2_BEARER", show_envvar=True)
# Click passes each declared option as a separate callback argument.
def main(
    osdd: str,
    *,
    output: Path,
    oci_hostname: str | None = None,
    oci_username: str | None = None,
    oci_password: str | None = None,
    authfile: Path | None,
    oauth2_bearer: str | None = None,
) -> None:
    """Convert one OSDD source into a pygeofilter file.

    Sources may be local paths or HTTP, HTTPS, file, or OCI URLs. Parent
    directories are created and an existing output file is overwritten after
    the JSON results URL has been validated and rendered.

    Args:
        osdd: Source pointing to the OSDD object.
        output: Destination pygeofilter path.
        oci_hostname: Registry host for explicit credentials; requires both
            username and password to take effect.
        oci_username: Registry username.
        oci_password: Registry password.
        authfile: Registry credentials file; missing files use empty credentials.
        oauth2_bearer: Bearer token applied to HTTP and HTTPS requests.

    Raises:
        SystemExit: With status 1 if reading, parsing, or writing fails.
    """
    session = requests.Session()

    def _mount_session(scheme: str, adapter: BaseAdapter) -> None:
        logger.debug(f"Mounting '{scheme}' scheme to '{type(adapter).__name__}'...")
        session.mount(scheme, adapter)
        logger.debug(f"Scheme '{scheme}' successfully mount to '{type(adapter).__name__}'")

    http_adapter = BearerAuthHTTPAdapter(oauth2_bearer) if oauth2_bearer else HTTPAdapter()
    _mount_session("http://", http_adapter)
    _mount_session("https://", http_adapter)
    _mount_session("file://", FileAdapter())

    authfile_path = Path(authfile) if authfile else None
    containers_auth = (
        ContainersAuth.get_instance(authfile_path)
        if authfile_path is not None and authfile_path.exists()
        else ContainersAuth(auths={})
    )

    if oci_hostname and oci_username and oci_password:
        containers_auth.add_auth(oci_hostname, oci_username, oci_password)
    _mount_session("oci://", OCIAdapter(containers_auth))

    start_time = time.time()
    exit_code = 0

    logger.info(
        f"Started at: {datetime.fromtimestamp(start_time).isoformat(timespec='milliseconds')}"
    )

    try:
        parsed = urlparse(osdd)
        is_url = f"{parsed.scheme}://" in session.adapters and (
            bool(parsed.netloc) or parsed.scheme == "file"
        )
    except ValueError:
        is_url = False
    location = osdd if is_url else Path(osdd).absolute().as_uri()

    try:
        response = session.get(location)
        response.raise_for_status()

        service = etree.fromstring(
            response.content,
            parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
        )
        logger.success(f"OSDD successfully parsed from {location}")

        logger.info(f"Saving OSDD to pygeofilter format to {output.absolute()}...")
        convert(service, output)

        logger.success(f"pygeofilter successfully dumped to {output.absolute()} file!")
    except Exception as error:
        exit_code = 1
        logger.exception(error)

    end_time = time.time()
    logger.info(f"Total time: {end_time - start_time:.4f} seconds")
    logger.info(
        f"Finished at: {datetime.fromtimestamp(end_time).isoformat(timespec='milliseconds')}"
    )

    if exit_code:
        sys.exit(exit_code)
