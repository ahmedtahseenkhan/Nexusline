# Aegis GRC

A modern, API-first, multi-tenant **Governance, Risk & Compliance** platform — a
clean-stack alternative to legacy PHP GRC tools (e.g. eramba).

| Concern | Choice |
|---|---|
| Backend | **Python 3.12 · FastAPI** (async) |
| ORM / migrations | **SQLAlchemy 2.0** + **Alembic** |
| Database | **PostgreSQL 16** with **Row-Level Security** for tenant isolation |
| Auth | OAuth2 Bearer (JWT), RBAC, per-org login |
| Cache / queue | **Redis** (+ background workers) |
| Frontend | **Next.js 14 · TypeScript · React** |
| Packaging | Docker + Docker Compose (K8s-ready) |

This repository ships a **working vertical slice** plus a second module:

- Multi-tenant **auth + RBAC** (per-org login, roles → permissions).
- **Risk Management** — register, inherent/residual scoring, treatment strategies,
  control/asset linkage, risk-acceptance workflow with expiry, review scheduling.
- **Compliance Management** — frameworks, requirements, control mapping
  ("map once, comply many"), per-framework **gap analysis** and compliance summary.

Every other GRC module follows this same template (models → schemas → RLS → router).

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then:

- API + interactive docs: <http://localhost:8080/docs>
- Web UI: <http://localhost:3000>
- Default seeded org → slug **`acme`**, admin **`admin@acme.com`** / **`ChangeMe123!`**

> Host ports: the API is published on **8080** and Postgres/Redis are kept internal
> to the compose network (8000/5432/6379 are commonly taken on dev machines). Adjust
> the `ports:` in [docker-compose.yml](docker-compose.yml) if you prefer different ones.

## Repository layout

```
backend/            FastAPI service
  app/
    core/           config, database (RLS), security, dependencies, RBAC
    models/         SQLAlchemy models (tenant, identity, risk domain)
    schemas/        Pydantic request/response models
    api/v1/         routers (auth, risks, controls, assets, …)
    services/       domain logic (risk scoring, …)
    db/             init + RLS policy application + seed
  alembic/          migrations (production workflow)
frontend/           Next.js app (login + risk register)
docker-compose.yml  postgres + redis + api + web
```

## Multi-tenancy model

Every tenant-scoped table carries a `tenant_id`. PostgreSQL **Row-Level Security**
(with `FORCE ROW LEVEL SECURITY`) enforces isolation in the database itself — the
app sets `app.current_tenant` per transaction and Postgres guarantees a request can
only ever see its own org's rows, even if application code has a bug. See
[backend/app/core/database.py](backend/app/core/database.py) and
[backend/app/db/rls.py](backend/app/db/rls.py).

## Development without Docker

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
export $(grep -v '^#' ../.env | xargs)
python -m app.db.init_db      # create tables + RLS + seed
uvicorn app.main:app --reload
```

## Production migrations

Dev uses `create_all` for speed. For production use Alembic:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
python -m app.db.rls   # (re)apply RLS policies after schema changes
```
