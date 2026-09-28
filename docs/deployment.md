# NexusLine GRC — On-Prem Deployment Runbook

This runbook covers installing NexusLine GRC on a customer-controlled host
(bank data centre, often **air-gapped**). The stack ships as Docker containers:

| Service    | Image                    | Role                                   |
|------------|--------------------------|----------------------------------------|
| `postgres` | `postgres:16-alpine`     | System of record (RLS-enforced)        |
| `redis`    | `redis:7-alpine`         | Cache / background queue                |
| `api`      | `nexusline-api` (built)  | FastAPI backend (internal port `8000`) |
| `web`      | `nexusline-web` (built)  | Next.js frontend (internal port `3000`)|
| `nginx`    | `nginx:1.27-alpine`      | TLS termination + reverse proxy        |

Only **nginx** is exposed to the network (`:80` redirect, `:443` TLS). Postgres,
Redis, api, and web are reachable only on the internal compose network.

All production commands use the production compose file:

```bash
docker compose -f docker-compose.prod.yml <command>
```

---

## 1. Prerequisites

- **Docker Engine 24+** and the **Docker Compose v2** plugin
  (`docker compose version`).
- ~4 vCPU / 8 GB RAM / 50 GB disk for a pilot (scale up for production load).
- **Building the web image needs ~2.5 GB of memory and ~6 GB of free disk.** On a
  smaller host, add swap and build one service at a time:

  ```bash
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # survives reboot
  bash deploy/redeploy.sh api && bash deploy/redeploy.sh web
  ```

  Without it the Next.js build stops with "JavaScript heap out of memory" and the
  image build fails on the missing `.next/standalone`.
- A DNS name for the host (e.g. `grc.bank.local`) and TLS certificates for it.
- **Either** outbound internet to pull/build images, **or** the offline bundle
  (see §8 Offline / Air-Gapped Install).

---

## 2. First-Time Install

### 2.1 Get the code / bundle onto the host
- Connected host: clone/copy the repository.
- Air-gapped host: transfer and extract the offline bundle (see §8), then work
  from inside the extracted `nexusline-offline-<version>/` directory.

### 2.2 Create and edit the environment file

```bash
cp .env.example .env
```

Edit `.env` and set, at minimum:

- `POSTGRES_PASSWORD` — strong DB owner password.
- `APP_DB_PASSWORD` — strong least-privilege runtime role password (see §3).
- `SECRET_KEY` — generate a real secret (see below).
- `CORS_ORIGINS` — the browser-facing HTTPS origin, e.g. `https://grc.bank.local`.
- `NEXT_PUBLIC_API_BASE_URL` — same HTTPS origin (nginx routes `/api` to the backend).
- `ENVIRONMENT=production`.

Generate a strong `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> The production compose passes through the on-prem env vars with sane defaults:
> `FILE_STORAGE_DIR`, `BACKUP_DIR`, `LICENSE_FILE`, `DEPLOYMENT_MODE`, `SMTP_*`,
> `LDAP_ENABLED`, `MFA_ENFORCEMENT`, `MFA_ENFORCEMENT_LOCKED`, `MFA_REQUIRED`, `ENFORCE_SEGREGATION_OF_DUTIES`,
> `SCHEDULER_ENABLED`. Override any of them in `.env`.
>
> Licensing is deliberately **not** in that list beyond the file location:
> whether the license is enforced, and which key validates it, are compiled into
> the image (see §8) and cannot be changed from `.env`.

### 2.3 TLS certificates

Place the server certificate and key at:

```
deploy/tls/fullchain.pem     # server cert (+ intermediate chain)
deploy/tls/privkey.pem       # private key
```

Use certificates issued by the bank's internal CA in production. For a **pilot**
you can generate a self-signed pair:

```bash
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout deploy/tls/privkey.pem \
  -out    deploy/tls/fullchain.pem \
  -subj "/CN=grc.bank.local" \
  -addext "subjectAltName=DNS:grc.bank.local"
```

### 2.4 Bring the stack up

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps        # all services healthy?
```

Browse to `https://grc.bank.local/`. The API health endpoint is proxied and
also probed by the container healthcheck at `/health`.

---

## 3. Least-Privilege Database Role

NexusLine separates two Postgres roles:

- **Owner / superuser** (`POSTGRES_USER`, default `aegis`) — used **only** for
  DDL, Alembic migrations, and bootstrap.
- **Runtime role** (`APP_DB_USER`, default `aegis_app`) — used by **all request
  traffic**. Row-Level Security constrains non-superusers, so the application
  connects as this role for tenant isolation to take effect.

Set a strong, distinct `APP_DB_PASSWORD` in `.env`. The runtime role is created
and granted during initialization; never point request traffic at the owner role.

---

## 4. First-Run Seeding & Admin

On first boot the API can bootstrap an initial organization and admin user from
the `SEED_*` variables in `.env`:

- `SEED_DATA=true` enables one-time seeding when the database is empty.
- `SEED_ORG_NAME`, `SEED_ORG_SLUG`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`.

**After the first successful login, change the admin password in the UI and set
`SEED_DATA=false`** (then `docker compose -f docker-compose.prod.yml up -d` to
apply). Leaving seeding on in production is a hardening finding.

> **`SEED_ADMIN_PASSWORD` applies only while the database is empty.** Seeding is
> one-time (`seed_if_empty`), so once the admin exists, editing that variable and
> restarting changes nothing — the value in `.env` is then a record of what the
> password *was*, not what it *is*. Every later change is made through the UI or the
> CLI below. If `.env` says one thing and sign-in fails with "Invalid credentials",
> this is almost always why.

### Recovering an account (no vendor round-trip)

The UI's own reset paths all need a session, so a lost admin password, a wiped
authenticator or a lockout can leave an on-prem install with no way in. The bank's
server administrator has one from the API container:

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account list
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account \
  show --org <slug> --email <address>          # why this account cannot sign in
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account \
  reset-password --org <slug> --email <address> [--clear-mfa]
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account \
  clear-mfa --org <slug> --email <address>     # lost authenticator, password intact
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account \
  unlock --org <slug> --email <address>        # clear a lockout
docker compose -f docker-compose.prod.yml exec api python -m app.tools.account \
  deactivate --org <slug> --email <address>    # a leaver; refuses the last active Admin
```

Notes for the runbook, and for the IT security review that will ask:

- The new password is **prompted for**, so it stays out of shell history and the
  process list. It must satisfy the configured password policy.
- `reset-password` also clears the failed-attempt counter and any lockout, and
  reactivates a deactivated account — a lost password and a lockout usually arrive
  together. `--clear-mfa` additionally drops the TOTP enrolment; **without it, an
  account with MFA on still needs its authenticator code**, so the reset alone will
  look like it did not work.
- Every action writes an `admin_*` event to the organisation's audit trail naming
  `cli:<os user>` as the actor, so an out-of-band reset is visible rather than silent.
- There is **no delete**: a user is an actor in the audit trail, so accounts are
  deactivated, never removed.
- The tool needs shell access to the application server, which already implies
  database access — it grants no privilege a host administrator lacked. Treat server
  shell access as the control, and review these audit events accordingly.

---

## 5. Upgrades (Alembic Migrations)

Schema changes ship as Alembic migrations. To upgrade an existing install:

```bash
# 1. Take a backup first (see §6).
docker compose -f docker-compose.prod.yml exec api python -m app.tools.backup create

# 2. Pull/load new images (see §8 for air-gapped), then recreate containers.
docker compose -f docker-compose.prod.yml up -d

# 3. Apply migrations.
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

> Run `alembic upgrade head` after every image update. Migrations are forward-only;
> restore from backup if an upgrade must be rolled back.

---

## 6. Backup & Restore

Backups and uploaded files persist in the `appdata` named volume, mounted at
`/data` inside the api container (`/data/uploads`, `/data/backups`).

### Create a backup

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.tools.backup create
```

This produces a Postgres dump (plus any file-storage manifest) under
`BACKUP_DIR` (`/data/backups`). Copy it off-host on a schedule:

```bash
docker compose -f docker-compose.prod.yml cp api:/data/backups ./backups-$(date +%F)
```

### Restore

Restore into a **fresh / empty** database (from a `pg_dump` custom-format dump):

```bash
# custom-format dump (.dump):
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < backup.dump

# or a plain SQL dump (.sql):
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < backup.sql
```

Then bring the api up and run `alembic upgrade head` to reconcile the schema.

> `app.tools.backup` is the supported CLI for consistent dumps; `pg_restore`/`psql`
> are the standard restore path. Test restores in a staging environment.

---

## 7. Offline / Air-Gapped Install

On a machine **with** internet + Docker, build the bundle:

```bash
./deploy/build-offline-bundle.sh 1.0.0
# -> produces nexusline-offline-1.0.0.tar.gz (images + compose + .env.example + deploy/)
```

Transfer `nexusline-offline-1.0.0.tar.gz` to the air-gapped host (USB / approved
transfer), then:

```bash
tar -xzf nexusline-offline-1.0.0.tar.gz
cd nexusline-offline-1.0.0
./deploy/load-offline-bundle.sh          # docker load all images
cp .env.example .env                     # then edit (secrets, hostnames)
# place TLS certs in deploy/tls/
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

No image pulls happen on the air-gapped host — every image (postgres, redis,
nginx, api, web) is loaded from the bundle.

---

## 8. Licensing

NexusLine uses **offline** licensing (Ed25519 signatures, no phone-home), so it
works in an air-gapped bank.

### 8.0 Client-side install

1. Place the signed license file at `deploy/license.key`.

That is the whole client-side procedure. `./deploy/` is mounted read-only into
the api container, so the default path (`/app/deploy/license.key`) resolves
automatically.

A release image refuses to start on an absent, invalid, or expired license.
There is no environment variable to relax that, and the trusted public key is
compiled into the image rather than read from disk, so replacing a key file or
editing `.env` does not bypass the gate. Locally built dev images
(`docker compose build`, which passes `PRODUCTION_BUILD=false`) run unlicensed.

### 8.0.1 Vendor-side key ceremony (once, ever)

```bash
cd backend
python -m app.tools.license keygen        # run exactly once for the product
```

This writes `vendor-keys/license_signing_key.pem` and embeds the matching public
key into `app/core/build.py`, which must then be committed — every image built
afterwards trusts that key.

- **Back up the private key out of band.** It cannot be recovered.
- **Never let it reach `deploy/`**, which is bind-mounted into client containers.
  Both `vendor-keys/` and `*license_signing_key.pem` are gitignored.
- Regenerating the keypair invalidates every license already issued to every
  client, which is why `keygen` refuses to overwrite without `--force`.

Issue a one-year license per client:

```bash
python -m app.tools.license sign --key vendor-keys/license_signing_key.pem \
  --to "Habib Bank Ltd" --plan enterprise --seats 250 --days 365 \
  --modules financial_crime,enterprise_risk --out deploy/license.key
python -m app.tools.license verify deploy/license.key
```

A client licence allows **one organisation** (the default `--organisations 1`):
the bank's IT team can run its own organisation from Settings → Organisations
but cannot add a second, so the same build never becomes a hosting platform on
a client's server. Only our own multi-tenant host gets a larger count:

```bash
python -m app.tools.license sign --key vendor-keys/license_signing_key.pem \
  --to "NexusLine Cloud" --plan saas --deployment saas --organisations 0 \
  --seats 0 --days 365 --out deploy/license.key      # 0 = unlimited
```

Self-service sign-up (`POST /auth/register-org`) is off everywhere unless
`ALLOW_SELF_REGISTRATION=true`; leave it off on client installations.

Release images are built with the enforcement flag stamped in (the default):

```bash
docker build -t nexusline-api:1.0.0 ./backend      # PRODUCTION_BUILD=true
```

The build fails if no vendor key is embedded, so a misbuilt image cannot ship
with the licensing gate silently disabled. `app/tools/license.py` — the keypair
generator and token signer — is excluded from the image by `.dockerignore` and
must never be shipped.

### 8.1 Module packaging (per-client entitlements)

Every client runs the **same build**; which modules are active is decided by the
license. When minting a license, list editions and/or individual module keys:

```bash
# Conventional bank (no Shariah module):
python -m app.tools.license sign --key vendor-keys/license_signing_key.pem \
  --to "Conventional Bank Ltd" --plan enterprise --seats 200 --days 365 \
  --modules financial_crime,enterprise_risk,resilience,audit,governance \
  --out license-conventional.key

# Islamic bank (adds Shariah governance):
python -m app.tools.license sign --key vendor-keys/license_signing_key.pem \
  --to "Islamic Bank Ltd" --plan enterprise --seats 200 --days 365 \
  --modules islamic_banking,financial_crime,enterprise_risk,audit \
  --out license-islamic.key

# Catalog of module keys and edition bundles:
python -m app.tools.license modules
```

Rules of thumb:

- **Omitting `--modules` unlocks everything** (also true for licenses minted
  before module packaging existed). Use `--modules core` to license only the
  base platform.
- A **disabled module is enforced server-side** (its API returns 403) and
  disappears from the sidebar; direct URLs show a "module not enabled" notice.
- The database schema is identical on every install — enabling a module later
  is a **license-file swap plus API restart**, no reinstall or migration.
- `DISABLED_MODULES` in `.env` (comma-separated module keys, e.g.
  `DISABLED_MODULES=esg,ai_assist`) hides licensed modules a client doesn't
  want to see; the license always remains the entitlement ceiling.
- The **Settings → System** admin view shows the full module matrix
  (on / hidden / unlicensed) and the license status.

Selling upgrades: a conventional bank that later opens an Islamic-banking
window just gets a re-signed license including `islamic_banking` — flip the
file, restart the api container, and the Shariah module appears with all its
seeded content intact.

---

## 9. Support

For diagnostics without granting remote access (see `docs/support-model.md`):

- **Health / system info** — `GET /health` and `GET /system/info` for a quick
  status and version/build readout.
- **Support bundle** — download the **redacted** support bundle from
  **Settings → Support**, or generate it on the host:

  ```bash
  docker compose -f docker-compose.prod.yml exec api python -m app.tools.support_bundle
  ```

  The bank reviews and forwards the bundle; no inbound access is required.

---

## 10. Production Hardening Checklist

- [ ] Change **all** default passwords: `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`,
      `SEED_ADMIN_PASSWORD`.
- [ ] Set a strong, unique `SECRET_KEY`.
- [ ] Install **real TLS certificates** (bank CA), not the self-signed pilot pair.
- [ ] Set `CORS_ORIGINS` to the exact HTTPS origin(s) only.
- [ ] Set `ENVIRONMENT=production`.
- [ ] Set `SEED_DATA=false` after the first run.
- [ ] Confirm Postgres is **not** published to the host (default in prod compose).
- [ ] Enable banking controls as required: `MFA_ENFORCEMENT=everyone` (and
      `MFA_ENFORCEMENT_LOCKED=true` where IT security policy owns the decision; an
      evaluation or UAT server may run `MFA_ENFORCEMENT=off`, never production),
      `ENFORCE_SEGREGATION_OF_DUTIES=true`, `LDAP_ENABLED` per directory setup.
- [ ] Provision at least **two** users with approval rights before go-live — with
      segregation of duties on, eight decisions (risk acceptance, exception approval,
      control audit, policy publication, SAR filing, charity approval and release,
      authority-matrix amendment) refuse when the maker is also the checker. A
      single-operator install cannot complete them.
- [ ] Deploying a release image (not a `PRODUCTION_BUILD=false` dev build) with a
      current `deploy/license.key`; renewal date diarised before expiry.
- [ ] Schedule off-host backups and periodically test a restore.
- [ ] **Load-test the install with the client's own volumes before go-live.** A bank's
      asset register is 6,000-10,000 records, not the three a demo carries, and capacity
      depends on `WEB_CONCURRENCY`, the database pool and Postgres `max_connections`
      together. The procedure, the tooling and the acceptance thresholds are in
      [load-testing.md](load-testing.md).
```
