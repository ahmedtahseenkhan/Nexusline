"""Executable continuous-control-monitoring checks.

:data:`CHECKS` maps a test's ``check_type`` to its :class:`~base.CheckSpec` (label,
parameter form, pass criterion, population and the ``run`` function);
:data:`CONNECTOR_KINDS` says how each connector type is reached and which settings and
secrets its form asks for. ``manual`` is a test whose runs are recorded by hand or
pushed by a monitoring tool (the phase 3 feed); it never runs on a schedule.

On-prem first: Active Directory over LDAP, scanner and SIEM exports from an import
folder, and internal HTTPS APIs. Cloud APIs (Azure AD, O365, AWS, Azure) use the generic
HTTPS JSON check and are for SaaS-tier deployments (docs/pakistan-banking-roadmap.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.ccm_checks import files, http_json, ldap_checks, vuln_import
from app.services.ccm_checks.base import (  # noqa: F401 - re-exported
    EVIDENCE_LINES,
    SAMPLE_CAP,
    CheckContext,
    CheckError,
    CheckOutcome,
    CheckSpec,
    ConnectionFailure,
    Param,
    UploadedFile,
    evaluate,
    exception_percent,
    pass_rate,
    threshold_text,
    validate_params,
    with_defaults,
)

MANUAL = CheckSpec(
    key="manual", label="Recorded by hand or pushed", group="Manual",
    description="Runs are recorded by a person or posted by a monitoring tool through the connector's feed; nothing runs on a schedule.",
    connector_types=(), input="none", params=(),
    pass_criterion="", population="",
)

CHECKS: dict[str, CheckSpec] = {
    spec.key: spec
    for spec in (MANUAL, *ldap_checks.SPECS, *vuln_import.SPECS, *files.SPECS, *http_json.SPECS)
}


@dataclass(frozen=True)
class ConnectorKind:
    kind: str  # ldap | http | file | push
    config_fields: tuple[Param, ...]
    secret_fields: tuple[Param, ...]
    note: str = ""


_LDAP = ConnectorKind(
    kind="ldap",
    config_fields=(
        Param("host", "Directory host", required=True, help="Domain controller or LDAP server, e.g. dc01.bank.local."),
        Param("port", "Port", "number", default=636, help="636 for LDAPS, 389 for LDAP with StartTLS."),
        Param("use_ssl", "Use LDAPS", "bool", default=True),
        Param("start_tls", "Use StartTLS (port 389)", "bool", default=False),
        Param("verify_tls", "Verify the server certificate", "bool", default=True),
        Param("ca_cert_path", "CA certificate file", help="Path on the server to the bank's CA bundle, when not in the system store."),
        Param("base_dn", "Base DN", required=True, help="e.g. DC=bank,DC=local."),
        Param("bind_dn", "Bind account", required=True, help="Read-only service account, e.g. CN=svc_grc_read,OU=Service,DC=bank,DC=local."),
    ),
    secret_fields=(Param("bind_password", "Bind password", required=True),),
)
_HTTP = ConnectorKind(
    kind="http",
    config_fields=(
        Param("base_url", "Base URL", required=True, help="e.g. https://siem.bank.local/api."),
        Param("auth", "Authentication", "select", default="bearer", options=("none", "bearer", "basic", "api_key_header")),
        Param("username", "Username (basic)"),
        Param("api_key_header", "API key header", default="X-API-Key"),
        Param("verify_tls", "Verify the server certificate", "bool", default=True),
        Param("health_path", "Test-connection path", help="A cheap GET used by Test connection, e.g. /health."),
    ),
    secret_fields=(Param("token", "Bearer token"), Param("password", "Password (basic)"), Param("api_key", "API key")),
)
_FILE = ConnectorKind(
    kind="file",
    config_fields=(
        Param("import_path", "Import folder", help="Folder inside the server's CCM import directory where exports are dropped."),
        Param("file_pattern", "File pattern", default="*", help="e.g. *.nessus, qualys_*.csv."),
    ),
    secret_fields=(),
    note="Runs read the newest matching file in the import folder, or a file uploaded with Run with file.",
)
_SIEM = ConnectorKind(
    kind="http",
    config_fields=_HTTP.config_fields + _FILE.config_fields,
    secret_fields=_HTTP.secret_fields,
    note="Pull log-source health from the SIEM API, or read an export from the import folder.",
)
_PUSH = ConnectorKind(kind="push", config_fields=(), secret_fields=(),
                      note="A monitoring tool posts results with the connector's feed token; nothing to connect to.")
_CLOUD_NOTE = "Cloud APIs are for SaaS-tier deployments; on-prem installations usually cannot reach them."

CONNECTOR_KINDS: dict[str, ConnectorKind] = {
    "active_directory": _LDAP,
    "siem": _SIEM,
    "vuln_scanner": _FILE,
    "csv_feed": _FILE,
    "webhook": _PUSH,
    "api": _HTTP,
    "cmdb": _HTTP,
    "core_banking": _HTTP,
    "edr_crowdstrike": _HTTP,
    "azure_ad": ConnectorKind("http", _HTTP.config_fields, _HTTP.secret_fields, _CLOUD_NOTE),
    "o365": ConnectorKind("http", _HTTP.config_fields, _HTTP.secret_fields, _CLOUD_NOTE),
    "cloud_aws": ConnectorKind("http", _HTTP.config_fields, _HTTP.secret_fields, _CLOUD_NOTE),
    "cloud_azure": ConnectorKind("http", _HTTP.config_fields, _HTTP.secret_fields, _CLOUD_NOTE),
}


def kind_of(connector_type: str | None) -> ConnectorKind:
    return CONNECTOR_KINDS.get(str(connector_type or ""), _PUSH)


def definition_errors(check_type: str, params: dict, connector_type: str | None) -> list[str]:
    """What is wrong with a test definition, in words (empty = fine). Pure."""
    spec = CHECKS.get(check_type)
    if spec is None:
        return [f"Check type: unknown '{check_type}'."]
    errors = validate_params(spec, with_defaults(spec, params))
    if spec.input == "connector" and not connector_type:
        errors.append(f"{spec.label} pulls from a connector: pick one.")
    if connector_type and spec.connector_types and connector_type not in spec.connector_types:
        errors.append(f"{spec.label} cannot run on a {connector_type.replace('_', ' ')} connector "
                      f"(use {', '.join(t.replace('_', ' ') for t in spec.connector_types)}).")
    return errors


def config_errors(connector_type: str | None, config: dict) -> list[str]:
    kind = kind_of(connector_type)
    known = {p.name for p in kind.config_fields}
    errors = [f"Setting '{k}' does not apply to this connector type." for k in (config or {}) if k not in known]
    for p in kind.config_fields:
        v = (config or {}).get(p.name)
        if p.kind == "number" and v not in (None, "") and base_num(v) is None:
            errors.append(f"{p.label}: must be a number.")
        if p.kind == "select" and v not in (None, "") and p.options and str(v) not in p.options:
            errors.append(f"{p.label}: must be one of {', '.join(p.options)}.")
    return errors


def base_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def secret_errors(connector_type: str | None, names) -> list[str]:
    allowed = {p.name for p in kind_of(connector_type).secret_fields}
    return [f"Secret '{n}' does not apply to this connector type." for n in (names or []) if n not in allowed]


def test_connection(connector_type: str | None, config: dict, secrets: dict, timeout: float, *,
                    ldap_factory=None, http_get=None, allow_private_urls: bool = True, import_root=None) -> str:
    """Reach the source with the stored settings; the sentence to show, or CheckError /
    ConnectionFailure. Synchronous (the API runs it in a worker thread)."""
    kind = kind_of(connector_type)
    if kind.kind == "ldap":
        return ldap_checks.connection_test(config, secrets, timeout, factory=ldap_factory)
    if kind.kind == "push":
        return "Push-only connector: there is nothing to connect to. Issue a feed token for the monitoring tool."
    messages = []
    if kind.kind == "http" and (config or {}).get("base_url"):
        ctx = CheckContext(parameters={}, connector_type=connector_type, config=config, secrets=secrets,
                           timeout=timeout, http_get=http_get, allow_private_urls=allow_private_urls)
        messages.append(http_json.connection_test(ctx))
    if (config or {}).get("import_path"):
        messages.append(files.folder_summary(config, import_root))
    if not messages:
        raise CheckError("Nothing to test: set the base URL" + (" or the import folder." if kind is _SIEM else ".")
                         if kind.kind == "http" else "Nothing to test: set the import folder.")
    return " ".join(messages)
