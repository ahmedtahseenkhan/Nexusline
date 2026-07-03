# NexusLine GRC — Support Model (Restricted / Air-Gapped Environments)

NexusLine is designed to be supported **without standing remote access** to the
bank's environment. Diagnostics flow *outbound* from the bank (health readouts
and a redacted support bundle the bank reviews before sending), so support works
even on fully air-gapped hosts with data-sovereignty constraints.

---

## Support Tiers

### Tier 0 — Self-Diagnostics (bank operator, no vendor contact)

The first line is built into the product and runs entirely inside the bank:

- **Health check** — `GET /health` returns liveness + environment. Also used by
  the container healthchecks and load balancers.
- **System info** — `GET /system/info` reports version/build, deployment mode,
  and enabled feature flags (MFA, LDAP, SoD, licensing) for a quick "what's
  running" snapshot.
- **Container status** — `docker compose -f docker-compose.prod.yml ps` and
  `... logs <service>` for immediate triage.

### Tier 1 — Redacted Support Bundle (asynchronous, no remote access)

When self-diagnostics are not enough, the bank generates a **redacted support
bundle** and sends it to the vendor. No inbound connection to the bank is
required.

**Workflow:**

1. The bank operator downloads the bundle from **Settings → Support**, or on the
   host:

   ```bash
   docker compose -f docker-compose.prod.yml exec api python -m app.tools.support_bundle
   ```

2. The bundle contains **redacted** diagnostics only — version/build, config
   *keys* (not secret values), recent application logs, migration state, and
   health/system output. Secrets, PII, and customer data are excluded/redacted.
3. The bank's security team **reviews** the bundle, then transfers it out via its
   approved channel (email/ticket/secure file transfer).
4. The vendor analyzes it offline and responds with guidance or a patch.

This is the default path for air-gapped banks: everything the vendor needs
travels in a reviewable artifact the bank controls.

### Tier 2 — Supervised Access (only when Tiers 0–1 are insufficient)

For issues that cannot be resolved from a bundle, escalate to a supervised
session under the bank's change-control:

- **Approved jump host** — the vendor connects through the bank's bastion/jump
  host, screen-shared or session-recorded, scoped to the incident window.
- **On-site** — a vendor engineer works on-premise under bank escort for
  fully isolated environments where no external connection is permitted.

All Tier 2 access is time-boxed, logged, and revoked at session end. No standing
credentials or persistent tunnels are provisioned.

---

## Access Tier Summary

| Tier | Mechanism                        | Remote access | Typical use                        |
|------|----------------------------------|---------------|------------------------------------|
| 0    | Health + system info + logs      | None          | First-line triage by bank operator |
| 1    | Redacted support bundle          | None (async)  | Most vendor-assisted issues        |
| 2a   | Approved jump host (supervised)  | Scoped/logged | Deep debugging under change-control|
| 2b   | On-site engineer                 | None          | Fully isolated / air-gapped sites  |

---

## SLA & Patch Cadence *(placeholders — finalize per contract)*

| Severity | Definition                              | Target response | Target workaround/fix |
|----------|-----------------------------------------|-----------------|-----------------------|
| S1       | Production down / data-integrity risk   | _TBD_           | _TBD_                 |
| S2       | Major function impaired, no workaround   | _TBD_           | _TBD_                 |
| S3       | Minor/degraded, workaround exists        | _TBD_           | _TBD_                 |
| S4       | Question / cosmetic / enhancement        | _TBD_           | _TBD_                 |

- **Security patches:** _TBD_ cadence; critical CVEs shipped out-of-band as an
  updated offline bundle (see `docs/deployment.md` §7).
- **Maintenance releases:** _TBD_ cadence, delivered as offline bundles for
  `docker load` + `alembic upgrade head`.
- **Support hours / contacts:** _TBD_ per the signed support agreement.
```
