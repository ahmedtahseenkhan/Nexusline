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
> `FILE_STORAGE_DIR`, `BACKUP_DIR`, `ENFORCE_LICENSE`, `LICENSE_FILE`,
> `LICENSE_PUBLIC_KEY_PATH`, `DEPLOYMENT_MODE`, `SMTP_*`, `LDAP_ENABLED`,
> `MFA_REQUIRED`, `ENFORCE_SEGREGATION_OF_DUTIES`, `SCHEDULER_ENABLED`.
> Override any of them in `.env`.

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

NexusLine uses **offline** licensing (Ed25519 signatures, no phone-home):

1. Place the signed license file at `deploy/license.key`.
2. Place the license public key at `deploy/license_pubkey.pem`.
3. Set `ENFORCE_LICENSE=true` in `.env`.

The `./deploy/` directory is mounted read-only into the api container, so the
default paths (`/app/deploy/license.key`, `/app/deploy/license_pubkey.pem`)
resolve automatically. With `ENFORCE_LICENSE=true`, the API refuses to start on
an absent, invalid, or expired license. Keep `ENFORCE_LICENSE=false` for dev.

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
- [ ] Enable banking controls as required: `MFA_REQUIRED=true`,
      `ENFORCE_SEGREGATION_OF_DUTIES=true`, `LDAP_ENABLED` per directory setup.
- [ ] If licensed: `ENFORCE_LICENSE=true` with key material in `deploy/`.
- [ ] Schedule off-host backups and periodically test a restore.
```
