"""HTTPS JSON checks and the outbound-request guard.

A check GETs a JSON document from the connector's API (``config.base_url`` + the test's
``path``) with the connector's credentials, picks a value out with the dotted selector,
and either compares one value to the expected value or counts the items of a list that
meet an exception rule.

**Private addresses (SSRF).** On-prem the sources are internal (core banking, CMDB,
SIEM), so private addresses must be reachable; on SaaS they must not, or a tenant could
make the server call into the hosting network. ``settings.ccm_allow_private_urls``
decides; unset, it follows ``settings.deployment_mode`` (on-prem: allowed; saas:
refused). When refused, every address the host resolves to must be public, and redirects
are not followed (a redirect cannot lead back inside).

Connector ``config``: ``base_url``, ``auth`` (none | bearer | basic | api_key_header),
``username`` (basic), ``api_key_header`` (header name), ``verify_tls`` (default true),
``health_path`` (for Test connection). Secrets: ``token`` | ``password`` | ``api_key``.
"""
from __future__ import annotations

import base64
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

from app.services.ccm_checks import selector
from app.services.ccm_checks.base import (
    CheckContext,
    CheckError,
    CheckOutcome,
    CheckSpec,
    COMPARISON_OPS,
    ConnectionFailure,
    Param,
    compare,
    label_of,
)

MAX_BODY_BYTES = 20 * 1024 * 1024


def private_urls_allowed() -> bool:
    from app.core.config import settings

    if settings.ccm_allow_private_urls is not None:
        return bool(settings.ccm_allow_private_urls)
    return (settings.deployment_mode or "on-prem").strip().lower() != "saas"


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified)


def url_refusal(url: str, *, allow_private: bool, resolve=None) -> str | None:
    """Why this URL may not be called, or None. Pure apart from DNS (``resolve`` is
    injectable: ``resolve(host) -> [ip, …]``)."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("https", "http"):
        return "Only http(s) URLs can be checked."
    if not parsed.hostname:
        return "The URL has no host."
    if parsed.username or parsed.password:
        return "Put credentials in the connector's secrets, not in the URL."
    if allow_private:
        return None
    if parsed.scheme != "https":
        return "This installation calls external APIs over HTTPS only."
    resolve = resolve or _resolve
    try:
        addresses = resolve(parsed.hostname)
    except OSError as exc:
        return f"Cannot resolve {parsed.hostname}: {exc}."
    if not addresses:
        return f"Cannot resolve {parsed.hostname}."
    blocked = [a for a in addresses if not _is_public(a)]
    if blocked:
        return (f"{parsed.hostname} resolves to a private or internal address ({blocked[0]}), which this "
                "installation does not call.")
    return None


def _resolve(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def auth_headers(config: dict, secrets: dict) -> dict[str, str]:
    kind = str(config.get("auth") or "none")
    if kind == "bearer":
        if not secrets.get("token"):
            raise CheckError("The connector uses a bearer token but none is set.")
        return {"Authorization": f"Bearer {secrets['token']}"}
    if kind == "basic":
        user, pw = str(config.get("username") or ""), secrets.get("password") or ""
        if not user:
            raise CheckError("The connector uses basic authentication but has no username.")
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}
    if kind == "api_key_header":
        header = str(config.get("api_key_header") or "X-API-Key")
        if not secrets.get("api_key"):
            raise CheckError("The connector uses an API key but none is set.")
        return {header: secrets["api_key"]}
    return {}


def default_http_get(url: str, headers: dict, params: dict | None, timeout: float, verify: bool) -> tuple[int, Any]:
    import httpx

    try:
        with httpx.Client(timeout=timeout, verify=verify, follow_redirects=False) as client:
            response = client.get(url, headers={"Accept": "application/json", **headers}, params=params or None)
    except httpx.HTTPError as exc:
        raise ConnectionFailure(f"Could not reach {urlparse(url).hostname}: {exc}.") from exc
    if len(response.content) > MAX_BODY_BYTES:
        raise CheckError(f"The response is larger than {MAX_BODY_BYTES // (1024 * 1024)} MB.")
    try:
        body = response.json() if response.content else None
    except ValueError:
        body = None
        if 200 <= response.status_code < 300:
            raise CheckError(f"{url} did not return JSON (status {response.status_code}).")
    return response.status_code, body


def target_url(config: dict, path: str | None) -> str:
    path = (path or "").strip()
    base = str(config.get("base_url") or "").strip()
    if path.startswith(("http://", "https://")):
        return path
    if not base:
        raise CheckError("The connector has no base URL.")
    return urljoin(base.rstrip("/") + "/", path.lstrip("/")) if path else base


def fetch_json(ctx: CheckContext, path: str | None, query: dict | None = None) -> Any:
    url = target_url(ctx.config, path)
    refusal = url_refusal(url, allow_private=ctx.allow_private_urls)
    if refusal:
        raise CheckError(refusal)
    getter = ctx.http_get or default_http_get
    status, body = getter(url, auth_headers(ctx.config, ctx.secrets), query, ctx.timeout,
                          ctx.config.get("verify_tls", True) not in (False, "false"))
    if status in (401, 403):
        raise ConnectionFailure(f"{urlparse(url).hostname} refused the credentials (HTTP {status}).")
    if status >= 300:
        raise CheckError(f"{url} answered HTTP {status}.")
    return body


def http_json_check(ctx: CheckContext) -> CheckOutcome:
    p = ctx.parameters
    body = fetch_json(ctx, p.get("path"), p.get("query") if isinstance(p.get("query"), dict) else None)
    path = str(p.get("selector") or "")
    value = selector.resolve(body, path)
    if value is selector.MISSING:
        raise CheckError(f"The selector '{path}' found nothing in the response.")
    mode = str(p.get("mode") or ("list" if isinstance(value, list) else "value"))
    if mode == "list":
        if not isinstance(value, list):
            raise CheckError(f"The selector '{path}' is not a list, so its items cannot be counted.")
        rule = p.get("exception_when") if isinstance(p.get("exception_when"), dict) else {}
        field = str(rule.get("field") or "")
        op = str(rule.get("op") or "is_true")
        label_field = str(p.get("label_field") or "")
        exceptions = []
        for item in value:
            actual = selector.select(item, field) if field else item
            if compare(actual, op, rule.get("value")):
                fields = ((label_field,) if label_field else ()) + ("name", "id", "hostname")
                row = {"item": label_of(item, *fields) if isinstance(item, dict) else str(item)}
                if field:
                    row[field] = actual if isinstance(actual, (str, int, float, bool)) or actual is None else str(actual)
                exceptions.append(row)
        return CheckOutcome(
            population=len(value), exceptions=exceptions,
            summary=f"{len(exceptions)} of {len(value)} item(s) at '{path}' where {field or 'item'} {op} {rule.get('value', '')}".rstrip(),
            metric_value=float(len(exceptions)), details={"selector": path, "mode": mode, "rule": rule},
        )
    op = str(p.get("op") or "==")
    expected = p.get("expected")
    ok = compare(value, op, expected)
    numeric = None
    try:
        numeric = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        numeric = None
    shown = value if isinstance(value, (str, int, float, bool)) or value is None else str(value)[:200]
    return CheckOutcome(
        population=1, exceptions=[] if ok else [{"selector": path, "value": shown, "expected": f"{op} {expected}"}],
        summary=f"'{path}' is {shown!r}; expected {op} {expected!r}: {'met' if ok else 'not met'}",
        metric_value=numeric, details={"selector": path, "mode": "value", "value": shown, "op": op, "expected": expected},
        passed=ok,
    )


def connection_test(ctx: CheckContext) -> str:
    health = ctx.config.get("health_path")
    fetch_json(ctx, health)
    return f"Reached {target_url(ctx.config, health)} with the connector's credentials."


def _validate(params: dict) -> list[str]:
    errors = []
    if str(params.get("mode") or "") == "list":
        rule = params.get("exception_when")
        if not isinstance(rule, dict) or not rule.get("op"):
            errors.append('Exception rule: a JSON object such as {"field": "mfa", "op": "is_false"}.')
        elif rule.get("op") not in COMPARISON_OPS:
            errors.append(f"Exception rule: op must be one of {', '.join(COMPARISON_OPS)}.")
    elif params.get("op") and params.get("op") not in COMPARISON_OPS:
        errors.append(f"Comparison: must be one of {', '.join(COMPARISON_OPS)}.")
    return errors


HTTP_CONNECTORS = ("api", "siem", "cmdb", "core_banking", "edr_crowdstrike", "azure_ad", "o365", "cloud_aws", "cloud_azure")

SPECS = (
    CheckSpec(
        key="http_json", label="HTTPS JSON check", group="Generic API",
        description=("Calls an API with the connector's credentials, picks a value with a dotted path "
                     "(data.items[*].status) and compares it, or counts the list items that break a rule."),
        connector_types=HTTP_CONNECTORS, input="connector",
        params=(
            Param("path", "Path", required=True, help="Appended to the connector's base URL, e.g. /api/v1/users?role=admin."),
            Param("selector", "Selector", help="Dotted path into the JSON: data.items, summary.failed, hosts[*].status. Blank = the whole body."),
            Param("mode", "Mode", "select", default="value", options=("value", "list"),
                  help="value: compare one value; list: count the items that break the exception rule."),
            Param("op", "Comparison (value mode)", "select", default="==", options=COMPARISON_OPS),
            Param("expected", "Expected value (value mode)"),
            Param("exception_when", "Exception rule (list mode)", "json",
                  help='{"field": "mfa_enabled", "op": "is_false"} — an item is an exception when the rule holds.'),
            Param("label_field", "Item label field (list mode)", help="Field that names an item in the exception sample."),
            Param("query", "Query parameters", "json", help='Extra query string, e.g. {"status": "active"}.'),
        ),
        pass_criterion="The selected value meets the comparison (value mode), or the exceptions stay within the threshold (list mode).",
        population="The items at the selector (list mode) or the one selected value.",
        run=http_json_check, validate=_validate,
    ),
)
