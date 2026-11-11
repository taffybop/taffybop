"""Explicit loopback-only development identity; never production authentication.

Only server configuration chooses the principal. Request headers, query strings
and upload fields cannot select another identity. Proxy headers are unsupported
in this profile so a forwarded request cannot masquerade as a local client.
"""

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from starlette.requests import Request


class LocalConfigurationError(ValueError):
    def __init__(self):
        super().__init__("Product API requires explicit local development configuration; hosted identity is unavailable.")


class LocalRequestDenied(ValueError):
    def __init__(self):
        super().__init__("This development library is available only through a direct local connection.")


@dataclass(frozen=True)
class LocalIdentity:
    owner: str

    def authorize(self, request: Request) -> str:
        client = request.client
        if client is None or not _loopback(client.host, allow_hostname=False):
            raise LocalRequestDenied()
        headers = request.headers
        if any(name == "forwarded" or name.startswith("x-forwarded-") for name in headers):
            raise LocalRequestDenied()
        if len(headers.getlist("host")) != 1 or len(headers.getlist("origin")) > 1:
            raise LocalRequestDenied()
        try:
            host = urlsplit("http://" + headers["host"])
            if (not _loopback(host.hostname) or host.username is not None or host.password is not None
                    or host.path or host.query or host.fragment or host.port == 0):
                raise LocalRequestDenied()
            origin = headers.get("origin")
            if origin is not None:
                parsed = urlsplit(origin)
                if (parsed.scheme != "http" or not _loopback(parsed.hostname)
                        or parsed.username is not None or parsed.password is not None
                        or parsed.path or parsed.query or parsed.fragment
                        or parsed.hostname != host.hostname or (parsed.port or 80) != (host.port or 80)):
                    raise LocalRequestDenied()
        except (KeyError, ValueError):
            raise LocalRequestDenied() from None
        if headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            raise LocalRequestDenied()
        return self.owner


def _loopback(host: str | None, *, allow_hostname: bool = True) -> bool:
    if allow_hostname and host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class LocalProductConfiguration:
    identity: LocalIdentity
    database_url: str
    artifact_root: Path


def load_local_configuration(environ: Mapping[str, str] | None = None) -> LocalProductConfiguration | None:
    values = os.environ if environ is None else environ
    mode = values.get("TAFFYBOP_PRODUCT_MODE", "disabled")
    if mode == "disabled":
        return None
    if (mode != "local_development" or values.get("TAFFYBOP_DEPLOYMENT") != "local"
            or values.get("TAFFYBOP_RUNTIME_PROFILE") != "product_worker_local"
            or any(values.get(name) for name in (
                "RENDER", "RENDER_SERVICE_ID", "DYNO", "K_SERVICE", "AWS_LAMBDA_FUNCTION_NAME",
                "WEBSITE_INSTANCE_ID", "CF_PAGES",
            ))):
        raise LocalConfigurationError()
    owner = values.get("TAFFYBOP_LOCAL_OWNER", "")
    dsn = values.get("TAFFYBOP_DATABASE_URL", "")
    root = Path(values.get("TAFFYBOP_ARTIFACT_ROOT", ""))
    if (not owner or len(owner) > 200 or any(not char.isprintable() for char in owner)
            or not dsn or not root.is_absolute() or ".." in root.parts):
        raise LocalConfigurationError()
    return LocalProductConfiguration(LocalIdentity(owner), dsn, root)
