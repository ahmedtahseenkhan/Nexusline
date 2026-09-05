"""Tenant isolation: the evidence a bank's auditor asks for before signing off SaaS.

The claim being tested is narrow and absolute: **one organisation's users cannot reach
another organisation's rows, even if the application asks for them.** That guarantee does
not live in the application — it lives in PostgreSQL row-level security, applied to every
tenant-scoped table and forced on even for the table owner, with the tenant read from a
transaction-local GUC that the connection sets per request.

Two layers of test, and they cover different failure modes:

* **Structural** (always runs). The way this guarantee actually breaks in practice is not
  a bad ``WHERE`` clause; it is a new model shipped with a ``tenant_id`` and no policy,
  because ``TENANT_SCOPED_TABLES`` is a hand-maintained list. That is one forgotten line
  in a pull request nobody reviews for it, and every query against the new table then
  reads across every organisation on the deployment. The first test below makes that
  omission fail CI.
* **Live** (skipped without a database). Two organisations, real rows, real connections:
  the proof itself, and what you run in front of a client.
"""
import os
import uuid

import pytest
from sqlalchemy import text

import app.models  # noqa: F401 - registers every table on the metadata
from app.core.database import Base
from app.db.rls import TENANT_SCOPED_TABLES, _PREDICATE, rls_ddl_statements
from app.models.base import TenantMixin

# Tables that carry a tenant_id but are intentionally NOT policy-protected, each with the
# reason. Anything else with a tenant_id must be in TENANT_SCOPED_TABLES.
_EXEMPT: dict[str, str] = {}


def _tenant_scoped_models() -> list[type]:
    return [
        mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantMixin)
    ]


# ------------------------------------------------------------------ structural ---
def test_every_tenant_scoped_table_has_a_policy():
    """The regression this exists to catch: a new model with a tenant_id, shipped
    without adding its table to the policy list. Nothing would error — the table would
    simply be readable across every organisation on the deployment."""
    protected = set(TENANT_SCOPED_TABLES)
    missing = sorted(
        model.__tablename__
        for model in _tenant_scoped_models()
        if model.__tablename__ not in protected and model.__tablename__ not in _EXEMPT
    )
    assert not missing, (
        "These tables carry a tenant_id but have no row-level security policy: "
        f"{missing}. Add them to app/db/rls.py:TENANT_SCOPED_TABLES."
    )


def test_the_policy_list_names_only_real_tables():
    """A typo in the list is a table silently left unprotected."""
    known = set(Base.metadata.tables)
    unknown = sorted(t for t in TENANT_SCOPED_TABLES if t not in known)
    assert not unknown, f"Policy list names tables that do not exist: {unknown}"


def test_the_policy_list_has_no_duplicates():
    duplicates = sorted({t for t in TENANT_SCOPED_TABLES if TENANT_SCOPED_TABLES.count(t) > 1})
    assert not duplicates, f"Duplicated entries: {duplicates}"


def test_isolation_fails_closed_when_no_tenant_is_set():
    """``NULLIF(..., '')::uuid`` is NULL when the GUC is unset or empty, and
    ``tenant_id = NULL`` matches nothing. A connection that forgets to set the tenant
    therefore sees zero rows rather than everybody's."""
    assert "NULLIF(current_setting('app.current_tenant', true), '')" in _PREDICATE
    assert _PREDICATE.startswith("tenant_id =")


def test_every_table_is_forced_not_merely_enabled():
    """ENABLE alone exempts the table owner, and migrations run as the owner. FORCE is
    what makes the policy apply to everyone, which is the whole guarantee."""
    statements = rls_ddl_statements()
    for table in TENANT_SCOPED_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in statements


def test_policies_guard_writes_as_well_as_reads():
    """Without WITH CHECK, a tenant could INSERT a row stamped with someone else's
    tenant_id — invisible to them afterwards, and corrupting the other organisation."""
    for statement in rls_ddl_statements():
        if statement.startswith("CREATE POLICY"):
            assert "USING" in statement and "WITH CHECK" in statement


def test_the_runtime_role_is_not_a_superuser():
    """RLS does not constrain a superuser at all. If the app ever connects as one, every
    policy above is decoration."""
    from app.core.config import settings

    assert settings.app_db_user
    assert settings.app_db_user != "postgres", (
        "The runtime role must be the least-privilege app role, not the superuser — "
        "row-level security does not apply to superusers."
    )


def test_the_platform_console_cannot_read_across_organisations():
    """The operator console lists organisations and counts their rows. The counts are
    gathered one tenant-scoped session at a time on purpose: a single grouped query
    across tenants is not expressible under RLS, and an endpoint that expressed one
    would be the hole the console exists to avoid."""
    import inspect

    from app.api.v1 import platform

    source = inspect.getsource(platform)
    assert "tenant_session(tenant_id)" in source, "counts must be read inside a tenant scope"
    # system_session() is tenant-less and therefore blind to tenant-scoped tables; it is
    # only ever used for the tenants registry itself, which carries no policy.
    counts = inspect.getsource(platform._counts)
    assert "system_session" not in counts


# ------------------------------------------------------------------------ live ---
_DB_URL = os.environ.get("TEST_DATABASE_URL")
_live = pytest.mark.skipif(
    not _DB_URL,
    reason="Set TEST_DATABASE_URL to run the live two-organisation isolation proof.",
)


@_live
@pytest.mark.asyncio
async def test_two_organisations_cannot_see_each_other():
    """The proof, against a real database: two organisations, one table, four checks.

    Reads are scoped, counts are scoped, a direct fetch by primary key of the *other*
    organisation's row returns nothing, and an attempt to write a row stamped with the
    other organisation's id is refused by the database rather than by us.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_DB_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def scoped(tenant_id):
        session = session_factory()
        await session.execute(
            text("SELECT set_config('app.current_tenant', :tid, true)"),
            {"tid": str(tenant_id) if tenant_id else ""},
        )
        return session

    from app.models.risk import Risk
    from app.models.tenant import Tenant
    from sqlalchemy import func, select

    async with session_factory() as registry:
        tenants = (await registry.scalars(select(Tenant).limit(2))).all()
    if len(tenants) < 2:
        pytest.skip("Needs at least two organisations; seed creates them by default.")
    first, second = tenants[0], tenants[1]

    marker = f"isolation-probe-{uuid.uuid4()}"
    session = await scoped(first.id)
    probe = Risk(
        tenant_id=first.id, title=marker, reference="ISO-PROBE",
        inherent_likelihood=1, inherent_impact=1,
    )
    session.add(probe)
    await session.commit()
    probe_id = probe.id

    try:
        other = await scoped(second.id)
        # 1. It is not in a listing.
        assert await other.scalar(select(Risk).where(Risk.title == marker)) is None
        # 2. It is not in a count.
        assert await other.scalar(
            select(func.count()).select_from(Risk).where(Risk.title == marker)
        ) == 0
        # 3. It is not reachable by primary key, which is the query an IDOR would make.
        assert await other.get(Risk, probe_id) is None
        # 4. It cannot be written into the other organisation either.
        with pytest.raises(Exception):
            other.add(Risk(
                tenant_id=first.id, title=f"{marker}-cross", reference="ISO-X",
                inherent_likelihood=1, inherent_impact=1,
            ))
            await other.commit()
        await other.rollback()

        # 5. A connection with no tenant set sees nothing at all — fails closed.
        blind = await scoped(None)
        assert await blind.scalar(
            select(func.count()).select_from(Risk).where(Risk.title == marker)
        ) == 0
        await blind.close()

        # And the owning organisation can still see its own row, so the test is
        # measuring isolation rather than a broken insert.
        owner = await scoped(first.id)
        assert await owner.get(Risk, probe_id) is not None
        await owner.close()
    finally:
        cleanup = await scoped(first.id)
        row = await cleanup.get(Risk, probe_id)
        if row is not None:
            await cleanup.delete(row)
            await cleanup.commit()
        await cleanup.close()
        await session.close()
        await engine.dispose()
