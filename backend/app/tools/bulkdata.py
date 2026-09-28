"""CLI: generate bank-scale volumes of data so the app can be load-tested honestly.

A demo org holds a handful of assets. A Pakistani bank's register is 6,000–10,000, each
one carrying classifications, handling labels, owners, a review history and links into
risks and controls — which is what actually makes a list page slow. This tool fills a
real organisation with that shape of data, in place, through the same engine and RLS the
API uses (so the rows are indistinguishable from entered ones).

  python -m app.tools.bulkdata loaduser --org acme      # an MFA-free account; also the rows' maker
  python -m app.tools.bulkdata generate --org acme --assets 10000
  python -m app.tools.bulkdata stats --org acme
  python -m app.tools.bulkdata purge --org acme

Every generated asset carries ``external_id = 'loadtest'``. ``purge`` removes exactly
those rows, their links (by cascade) and the activity trail about them — it can never
delete a record a client typed.
Run it against a test or UAT database, never production.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, insert, select, text

from app.core.database import system_session, tenant_session
from app.core.security import hash_password
from app.models.asset import (
    Asset,
    AssetClassification,
    AssetDependency,
    AssetLabel,
    AssetMediaType,
    AssetReview,
    AssetTag,
    asset_classification_links,
    asset_tag_links,
)
from app.models.control import Control, control_assets
from app.models.enums import (
    AssetClass,
    AssetDependencyType,
    AssetEnvironment,
    AssetReviewStatus,
    Criticality,
    DiscoverySource,
    ReviewFrequency,
    WorkflowStatus,
)
from app.models.audit import AuditLog
from app.models.identity import Role, User, user_roles
from app.models.organization import BusinessUnit
from app.models.risk import Risk, risk_assets
from app.models.tenant import Tenant

#: Stamped on every generated asset so ``purge`` is exact.
MARKER = "loadtest"
#: Rows per INSERT. 500 keeps each statement well inside Postgres' parameter limit.
CHUNK = 500

# Name pools that read like a bank's register rather than "Asset 4711" — search and sort
# behave differently on realistic text (shared prefixes, varied length, mixed case).
_IT_KINDS = [
    "Core Banking Node", "ATM Switch", "Card Management Server", "SWIFT Gateway",
    "Internet Banking Web Node", "Mobile Banking API Node", "Branch File Server",
    "Domain Controller", "Oracle DB Cluster Node", "MS SQL Cluster Node",
    "Backup Appliance", "Tape Library", "Core Router", "Distribution Switch",
    "Branch Firewall", "WAF Appliance", "HSM", "Load Balancer", "SIEM Collector",
    "Email Gateway", "Proxy Server", "VDI Host", "Hypervisor Host", "NAS Head",
    "RTGS Terminal", "Cheque Truncation Scanner", "Teller Workstation", "Kiosk",
]
_INFO_KINDS = [
    "Customer Master Data", "Account Ledger", "Card Transaction Records",
    "KYC Document Store", "Loan Application Files", "AML Alert Data",
    "Payroll Records", "Treasury Position Data", "Trade Finance Documents",
    "Branch Cash Register", "Internet Banking Credentials", "Mobile App Session Data",
    "Call Centre Recordings", "CCTV Footage", "Audit Working Papers",
    "Regulatory Return Data", "Credit Bureau Extracts", "Employee HR Files",
]
_SITES = [
    "Head Office, Karachi", "Data Centre, Karachi", "DR Site, Islamabad",
    "Regional Office, Lahore", "Regional Office, Peshawar", "Branch, Faisalabad",
    "Branch, Multan", "Branch, Quetta", "Branch, Hyderabad", "Cloud (Azure UAE North)",
]
_MAKERS = ["Dell", "HP", "Cisco", "IBM", "Oracle", "Fortinet", "Thales", "NetApp", "Huawei"]
_OS = ["RHEL 9.4", "RHEL 8.10", "Windows Server 2022", "Windows Server 2019",
       "Ubuntu 24.04 LTS", "AIX 7.3", "VMware ESXi 8.0", "Cisco IOS-XE 17.9", "n/a"]
_OWNERS = ["Head of IT Operations", "Chief Information Security Officer", "Head of Retail Banking",
           "Head of Treasury", "Head of Compliance", "Head of Operations", "Head of HR"]
_CRITS = list(Criticality)
_ENVS = [AssetEnvironment.production] * 6 + [
    AssetEnvironment.dr, AssetEnvironment.uat, AssetEnvironment.staging, AssetEnvironment.development
]
_FREQS = [ReviewFrequency.annual, ReviewFrequency.semiannual, ReviewFrequency.quarterly]
_CYCLE_DAYS = {ReviewFrequency.annual: 365, ReviewFrequency.semiannual: 182, ReviewFrequency.quarterly: 91}
_WORKFLOWS = [WorkflowStatus.approved] * 6 + [WorkflowStatus.draft] * 3 + [WorkflowStatus.in_review]


async def _tenant_id(slug: str) -> uuid.UUID:
    async with system_session() as db:
        tid = await db.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tid is None:
        raise SystemExit(f"No organisation with slug '{slug}'. Check Settings -> Organisations.")
    return tid


async def _ids(db, model, limit: int = 300) -> list[uuid.UUID]:
    return list((await db.scalars(select(model.id).limit(limit))).all())


async def _live_ids(db, model, limit: int = 300) -> list[uuid.UUID]:
    """Ids of non-archived rows — what a list page would actually show as a link."""
    return list((await db.scalars(select(model.id).where(model.deleted.is_(False)).limit(limit))).all())


def _sample(pool: list, n: int) -> list:
    """Up to ``n`` distinct members of ``pool`` (empty pool -> nothing)."""
    if not pool:
        return []
    return random.sample(pool, min(n, len(pool)))


def _asset_row(i: int, tid: uuid.UUID, rng: random.Random, lookups: dict) -> dict:
    """One asset, ~60/40 IT vs information — the split a bank register usually lands on."""
    is_it = rng.random() < 0.6
    today = date.today()
    # About a quarter of the register is overdue for review; last review is one cycle
    # before the next, as completing a review sets it.
    frequency = rng.choice(_FREQS)
    cycle = _CYCLE_DAYS[frequency]
    next_review = today + timedelta(days=rng.randint(-120, cycle))
    kind = rng.choice(_IT_KINDS if is_it else _INFO_KINDS)
    name = f"{kind} {i:05d}"
    row = {
        "id": uuid.uuid4(),
        "tenant_id": tid,
        "name": name,
        "description": f"{kind} recorded for capacity testing at bank scale. Site: {rng.choice(_SITES)}.",
        "asset_class": AssetClass.it_asset if is_it else AssetClass.information_asset,
        "media_type_id": rng.choice(lookups["media_types"]) if lookups["media_types"] else None,
        "label_id": rng.choice(lookups["labels"]) if lookups["labels"] else None,
        "owner_id": rng.choice(lookups["units"]) if lookups["units"] else None,
        "guardian_id": rng.choice(lookups["units"]) if lookups["units"] else None,
        "user_id": rng.choice(lookups["units"]) if lookups["units"] else None,
        "confidentiality": rng.choice(_CRITS),
        "integrity": rng.choice(_CRITS),
        "availability": rng.choice(_CRITS),
        "criticality": rng.choice(_CRITS),
        "business_value": rng.choice(_CRITS),
        "potential_liabilities": "",
        "information_owner": "" if is_it else rng.choice(_OWNERS),
        "data_categories": "" if is_it else rng.choice(
            ["PII, financial", "PII, transactional", "financial", "PII, biometric", "internal"]
        ),
        "records_volume": "" if is_it else f"~{rng.randint(1, 9)}.{rng.randint(0, 9)}M records",
        "self_assessed": (not is_it) and rng.random() < 0.6,
        "assessed_by": "" if is_it else rng.choice(_OWNERS),
        "assessed_date": None if is_it else today - timedelta(days=rng.randint(10, 600)),
        "replacement_cost": rng.choice([0, 250_000, 1_200_000, 8_500_000, 45_000_000]) if is_it else 0,
        "currency": "PKR",
        "rto_hours": rng.choice([1, 2, 4, 8, 24, 72]),
        "rpo_hours": rng.choice([0, 1, 4, 24]),
        "environment": rng.choice(_ENVS) if is_it else AssetEnvironment.not_applicable,
        "location": rng.choice(_SITES),
        "hostname": f"{'srv' if is_it else 'dat'}-{i:05d}.bank.local" if is_it else "",
        "ip_address": f"10.{rng.randint(0, 254)}.{rng.randint(0, 254)}.{rng.randint(1, 254)}" if is_it else "",
        "serial_number": f"SN{rng.randint(10**9, 10**10 - 1)}" if is_it else "",
        "manufacturer": rng.choice(_MAKERS) if is_it else "",
        "model_number": f"M{rng.randint(100, 999)}-{rng.choice('ABCDEFG')}" if is_it else "",
        "os_version": rng.choice(_OS) if is_it else "",
        "discovery_source": DiscoverySource.manual,
        "external_id": MARKER,
        "auto_discovered": False,
        "last_seen": today - timedelta(days=rng.randint(0, 30)),
        "review_frequency": frequency,
        "next_review_date": next_review,
        "last_review_date": next_review - timedelta(days=cycle),
        "expired_reviews": 1 if next_review < today else 0,
        "workflow_status": rng.choice(_WORKFLOWS),
        "workflow_owner": rng.choice(_OWNERS),
        "deleted": False,
    }
    return row


async def _people(db, maker_email: str) -> tuple[Any, Any]:
    """The maker (``maker_email``, the load-test service account by default) and an
    approver: an active Admin who is not the maker. Either may be None."""
    maker = await db.scalar(select(User).where(User.email == maker_email))
    approver = None
    for user in (await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.created_at))).all():
        if (maker is None or user.id != maker.id) and "Admin" in user.role_names:
            approver = user
            break
    return maker, approver


def _trail(rows: list[dict], tid: uuid.UUID, maker: Any, approver: Any) -> list[dict]:
    """Audit rows for generated assets, as the application writes them: ``create`` by the
    maker; ``workflow_submit`` by the maker for rows in review or approved; and
    ``workflow_approve`` by the approver for approved rows."""
    if maker is None:
        return []
    out: list[dict] = []

    def row(asset: dict, action: str, actor: Any, summary: str, changes: dict | None = None) -> dict:
        return {"id": uuid.uuid4(), "tenant_id": tid, "actor_id": actor.id, "actor_email": actor.email,
                "action": action, "entity_type": "asset", "entity_id": asset["id"],
                "summary": summary[:500], "changes": changes or {}}

    for a in rows:
        state = a["workflow_status"]
        out.append(row(a, "create", maker, f"Created asset {a['name']}"))
        if state in (WorkflowStatus.in_review, WorkflowStatus.approved):
            out.append(row(a, "workflow_submit", maker, f"Submitted for review: asset {a['name']}",
                           {"from": "draft", "to": "in_review"}))
        if state == WorkflowStatus.approved and approver is not None:
            out.append(row(a, "workflow_approve", approver, f"Approved: asset {a['name']}",
                           {"from": "in_review", "to": "approved"}))
    return out


async def generate(slug: str, count: int, per_risk: int, per_control: int, estate_controls: int,
                   seed: int, maker_email: str) -> None:
    tid = await _tenant_id(slug)
    rng = random.Random(seed)
    started = time.monotonic()

    async with tenant_session(tid) as db:
        maker, approver = await _people(db, maker_email)
        if maker is None:
            print(f"note: no user '{maker_email}' — run 'loaduser' first. Without a maker the rows get "
                  "no activity trail, and approving them is refused (nobody to check four-eyes against).")
        elif approver is None:
            print("note: no Admin other than the maker — approved rows get no approver on file.")
        lookups = {
            "media_types": await _ids(db, AssetMediaType),
            "labels": await _ids(db, AssetLabel),
            "classifications": await _ids(db, AssetClassification),
            "tags": await _ids(db, AssetTag),
            "units": await _live_ids(db, BusinessUnit),
            "risks": await _live_ids(db, Risk),
            "controls": await _live_ids(db, Control),
        }
        thin = [k for k in ("media_types", "labels", "classifications", "tags", "units",
                            "risks", "controls") if not lookups[k]]
        if thin:
            print(f"note: this org has no {', '.join(thin)} — those links will be empty, so the "
                  f"list page will be measured lighter than a real register.")

        existing = await db.scalar(
            select(func.count()).select_from(Asset).where(Asset.external_id == MARKER)
        ) or 0
        first = existing + 1

        it_ids: list[uuid.UUID] = []
        info_ids: list[uuid.UUID] = []
        created_rows: list[dict] = []
        made = 0
        for start in range(0, count, CHUNK):
            n = min(CHUNK, count - start)
            rows = [_asset_row(first + start + k, tid, rng, lookups) for k in range(n)]
            await db.execute(insert(Asset), rows)
            created_rows.extend(rows)

            link_rows: dict[object, list[dict]] = {}

            def add(table, values: list[dict]) -> None:
                if values:
                    link_rows.setdefault(table, []).extend(values)

            for row in rows:
                aid = row["id"]
                (it_ids if row["asset_class"] is AssetClass.it_asset else info_ids).append(aid)
                add(asset_classification_links, [
                    {"asset_id": aid, "asset_classification_id": c}
                    for c in _sample(lookups["classifications"], rng.randint(1, 3))
                ])
                add(asset_tag_links, [
                    {"asset_id": aid, "asset_tag_id": t}
                    for t in _sample(lookups["tags"], rng.randint(0, 2))
                ])
                # A closed review plus the next scheduled one: the history a detail page shows.
                add(AssetReview.__table__, [
                    {
                        "id": uuid.uuid4(), "tenant_id": tid, "asset_id": aid,
                        "reviewer": row["workflow_owner"], "scheduled_date": row["last_review_date"],
                        "actual_date": row["last_review_date"], "status": AssetReviewStatus.completed,
                        "outcome": "No change", "comments": "",
                    },
                    {
                        "id": uuid.uuid4(), "tenant_id": tid, "asset_id": aid,
                        "reviewer": row["workflow_owner"], "scheduled_date": row["next_review_date"],
                        "actual_date": None, "status": AssetReviewStatus.scheduled,
                        "outcome": "", "comments": "",
                    },
                ])
            for table, values in link_rows.items():
                for at in range(0, len(values), CHUNK):
                    await db.execute(insert(table), values[at:at + CHUNK])

            made += n
            print(f"  {made}/{count} assets", end="\r", flush=True)

        # Information asset -> IT asset dependencies, so derived criticality and the
        # dependency panels have something to compute over.
        deps: list[dict] = []
        seen: set[tuple] = set()
        for info_id in info_ids:
            for it_id in _sample(it_ids, rng.randint(1, 3)):
                rel = rng.choice(list(AssetDependencyType))
                key = (info_id, it_id, rel)
                if key in seen:
                    continue
                seen.add(key)
                deps.append({
                    "id": uuid.uuid4(), "tenant_id": tid, "information_asset_id": info_id,
                    "it_asset_id": it_id, "relationship_type": rel, "notes": "",
                })
        for at in range(0, len(deps), CHUNK):
            await db.execute(insert(AssetDependency), deps[at:at + CHUNK])

        # Risks and controls link a realistic number of assets, decided per risk and per
        # control — not per asset, which with a handful of live risks linked every risk to
        # thousands of assets and made every risk page and asset write measure a fiction.
        # A few estate-wide controls (endpoint protection, patching) do cover thousands,
        # because banks have those.
        all_ids = it_ids + info_ids
        risk_links = [
            {"risk_id": r, "asset_id": a}
            for r in lookups["risks"] for a in _sample(all_ids, rng.randint(3, per_risk))
        ]
        estate = set(_sample(lookups["controls"], estate_controls))
        control_links = [
            {"control_id": c, "asset_id": a}
            for c in lookups["controls"]
            for a in (_sample(it_ids, int(len(it_ids) * 0.8)) if c in estate
                      else _sample(all_ids, rng.randint(3, per_control)))
        ]
        for table, rows_ in ((risk_assets, risk_links), (control_assets, control_links)):
            for at in range(0, len(rows_), CHUNK):
                await db.execute(insert(table), rows_[at:at + CHUNK])

        # An activity trail like the application's own: created by a maker, submitted by
        # them, approved by someone else. Without it four-eyes has nobody to compare the
        # approver with, and approvals of these rows are refused (by design).
        trail = _trail(created_rows, tid, maker, approver)
        for at in range(0, len(trail), CHUNK):
            await db.execute(insert(AuditLog), trail[at:at + CHUNK])

    took = time.monotonic() - started
    print(f"\nInserted {count} assets ({len(it_ids)} IT, {len(info_ids)} information) "
          f"and {len(deps)} dependencies into '{slug}' in {took:.1f}s.")
    print("Run ANALYZE so the planner sees the new volume:")
    print("  docker compose exec postgres psql -U aegis -d aegis -c 'ANALYZE;'")


async def loaduser(slug: str, email: str, password: str) -> None:
    """Create (or reset) a service account a load test can sign in as.

    A load driver cannot complete TOTP, and a bank's real admin accounts should keep MFA
    on. So the test gets its own account: MFA off, not locked, holding every role in the
    organisation so no call in the mix returns 403 and flatters the numbers. Create it on
    a test or UAT install only, and delete it afterwards.
    """
    tid = await _tenant_id(slug)
    async with tenant_session(tid) as db:
        user = await db.scalar(select(User).where(User.email == email))
        role_ids = list((await db.scalars(select(Role.id))).all())
        if user is None:
            user = User(
                tenant_id=tid, email=email, full_name="Load Test Service Account",
                hashed_password=hash_password(password), is_active=True, auth_source="local",
            )
            db.add(user)
            await db.flush()
            action = "Created"
        else:
            user.hashed_password = hash_password(password)
            action = "Reset"
        user.is_active = True
        user.mfa_enabled = False
        user.mfa_secret = ""
        user.mfa_grace_until = None
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.execute(user_roles.delete().where(user_roles.c.user_id == user.id))
        if role_ids:
            await db.execute(
                insert(user_roles), [{"user_id": user.id, "role_id": r} for r in role_ids]
            )
    print(f"{action} {email} in '{slug}' with {len(role_ids)} roles, MFA off.")
    print(f"  python scripts/loadtest.py --org {slug} --email {email} --password '{password}'")


async def stats(slug: str) -> None:
    tid = await _tenant_id(slug)
    async with tenant_session(tid) as db:
        total = await db.scalar(select(func.count()).select_from(Asset).where(Asset.deleted.is_(False)))
        generated = await db.scalar(select(func.count()).select_from(Asset).where(Asset.external_id == MARKER))
        by_class = (await db.execute(
            select(Asset.asset_class, func.count()).where(Asset.deleted.is_(False)).group_by(Asset.asset_class)
        )).all()
        # Pure association tables carry no tenant_id, so RLS cannot scope them and a bare
        # COUNT(*) would report every organisation's rows. Count through this org's assets.
        own = select(Asset.id).scalar_subquery()
        links = {}
        for label, table in (
            ("asset_classifications_assets", asset_classification_links),
            ("asset_tag_links", asset_tag_links),
            ("risk_assets", risk_assets),
            ("control_assets", control_assets),
            ("asset_reviews", AssetReview.__table__),
        ):
            links[label] = await db.scalar(
                select(func.count()).select_from(table).where(table.c.asset_id.in_(own))
            )
        links["asset_dependencies"] = await db.scalar(
            select(func.count()).select_from(AssetDependency.__table__)
        )
        per_risk = (await db.execute(text(
            "SELECT coalesce(max(n), 0), coalesce(round(avg(n)), 0) FROM (SELECT count(*) n FROM risk_assets ra "
            "JOIN assets a ON a.id = ra.asset_id GROUP BY ra.risk_id) t"))).one()
        per_control = (await db.execute(text(
            "SELECT coalesce(max(n), 0), coalesce(round(avg(n)), 0) FROM (SELECT count(*) n FROM control_assets ca "
            "JOIN assets a ON a.id = ca.asset_id GROUP BY ca.control_id) t"))).one()
        size = await db.scalar(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
    print(f"organisation : {slug}")
    print(f"assets (live): {total}   of which generated: {generated}")
    for cls, n in by_class:
        print(f"  {getattr(cls, 'value', cls):<20} {n}")
    print("link rows visible to this org:")
    for label, n in links.items():
        print(f"  {label:<30} {n}")
    print(f"assets per risk   : max {per_risk[0]}, mean {per_risk[1]}")
    print(f"assets per control: max {per_control[0]}, mean {per_control[1]}")
    print(f"database size: {size}")


async def purge(slug: str) -> None:
    tid = await _tenant_id(slug)
    async with tenant_session(tid) as db:
        ids = list((await db.scalars(select(Asset.id).where(Asset.external_id == MARKER))).all())
        if not ids:
            print(f"Nothing to purge in '{slug}'.")
            return
        # Hard delete; link rows go with them via ON DELETE CASCADE. The activity trail
        # about them goes too — the rows ``generate`` wrote and anything done to these
        # test records since — or it would outlive them as orphans.
        trail = 0
        for at in range(0, len(ids), CHUNK):
            chunk = ids[at:at + CHUNK]
            trail += (await db.execute(
                text("DELETE FROM audit_logs WHERE entity_type = 'asset' AND entity_id = ANY(:ids)"),
                {"ids": chunk},
            )).rowcount or 0
            await db.execute(text("DELETE FROM assets WHERE id = ANY(:ids)"), {"ids": chunk})
    print(f"Purged {len(ids)} generated assets and {trail} activity-trail rows about them from '{slug}'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.bulkdata",
        description="Generate, measure or remove bank-scale test data.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="insert generated assets into an organisation")
    gen.add_argument("--org", required=True, help="organisation slug (e.g. acme)")
    gen.add_argument("--assets", type=int, default=10_000, help="how many to insert (default 10000)")
    gen.add_argument("--per-risk", type=int, default=40,
                     help="most assets one risk links (default 40; a real risk links tens)")
    gen.add_argument("--per-control", type=int, default=120,
                     help="most assets one ordinary control protects (default 120)")
    gen.add_argument("--estate-controls", type=int, default=2,
                     help="controls that cover ~80%% of IT assets, like endpoint protection (default 2)")
    gen.add_argument("--maker", default="loadtest@example.com",
                     help="the user recorded as having entered the rows (default %(default)s)")
    gen.add_argument("--seed", type=int, default=1337, help="RNG seed, for a repeatable dataset")

    lu = sub.add_parser("loaduser", help="create/reset an MFA-free service account for the driver")
    lu.add_argument("--org", required=True)
    lu.add_argument("--email", default="loadtest@example.com", help="account email (default %(default)s)")
    lu.add_argument("--password", default="LoadTest123!")

    st = sub.add_parser("stats", help="row counts and database size for an organisation")
    st.add_argument("--org", required=True)

    pg = sub.add_parser("purge", help="delete every generated asset from an organisation")
    pg.add_argument("--org", required=True)
    pg.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        if args.assets < 1:
            print("--assets must be at least 1", file=sys.stderr)
            return 2
        asyncio.run(generate(args.org, args.assets, args.per_risk, args.per_control,
                             args.estate_controls, args.seed, args.maker))
    elif args.cmd == "loaduser":
        asyncio.run(loaduser(args.org, args.email, args.password))
    elif args.cmd == "stats":
        asyncio.run(stats(args.org))
    else:
        if not args.yes:
            reply = input(f"Delete every generated asset in '{args.org}'? [y/N] ").strip().lower()
            if reply != "y":
                print("Cancelled.")
                return 1
        asyncio.run(purge(args.org))
    return 0


if __name__ == "__main__":
    sys.exit(main())
