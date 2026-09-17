"""Move generated risks made before the candidate queue into it (re-check F-24).

Before phase 3 the generator wrote one register risk per asset × scenario pair. The queue
now groups pairs by scenario + process + business unit and only an accepted candidate
reaches the register, but the risks written earlier are still there: the reviewed tenant
held 74 of them, each titled "<scenario> <asset>", each linked to one asset, none owned.

This module finds them, says what would happen to each (``GET
/risk-proposals/legacy-migration``) and, when a person confirms, does it (``POST``):

* **Recognised** — a live risk whose title matches a library scenario's title pattern
  (``risk_scenarios.title_patterns``) naming the one asset it links (or, with no link
  left, an archived asset of that name), outside the hierarchy (``level`` and parent
  unset), and not already tied to the queue (no candidate promoted to it or rebuilt
  from it).
* **Kept** — recognised but worked on since it was generated. Any of: status or
  approval state beyond draft; an owner or treatment owner; a treatment strategy,
  assessment rationale, residual or target scores; controls beyond those the generator
  would have linked (the asset's own and the scenario's); any other live link (issue,
  KRI, incident, policy, child risk…); treatment actions, acceptance requests, impact
  dimension scores, comments, attachments, attestations or approval requests; a person's
  change in its activity trail (the create entry aside); or more than one asset. A
  risk whose title names an asset it does not link is kept too — the title or the link
  is wrong, and a person should decide which. Each kept risk is listed with its reasons.
* **Dropped** — recognised and untouched, but not worth a candidate: its asset was
  deleted, the scenario does not fit the asset's kind (fraud against a firewall), or the
  candidate for its scope was already rejected. Archived, restorable, no candidate.
* **Moved** — everything else, grouped by the queue's own key. A group becomes a new
  pending candidate, or joins the one already waiting with that key, carrying every
  asset, the worst scores and the scenario's and the risks' control references. The
  first risk is the candidate's ``source_risk_id``; every moved risk's archive entry in
  the activity trail names the candidate. Archived, restorable.

A scope whose candidate was accepted and whose risk is live keeps the legacy risk: two
register risks now cover the same thing, and only a person can say which one goes.

Rejecting a candidate built this way leaves its risks archived; accepting it promotes
it like any other. Restoring an archived risk puts it back in the register and, because
the restore is a person's change in its trail, it is never moved again.

Restoring a moved risk must not leave the same risk waiting in the queue as well
(:func:`release_on_restore`, phase 4). When its candidate is still pending: if the
migration created that candidate and every risk moved into it is live again, the
candidate is withdrawn (rejected, "Source risk restored"); otherwise only the restored
risk's assets leave it — those no still-archived source also carries — and a candidate
left with no assets is withdrawn too. A decided candidate is left alone.

The decisions are pure (:func:`recognise`, :func:`edit_reasons`, :func:`plan_migration`)
and unit-tested without a database; :func:`load_plan` and :func:`apply` do the I/O.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.enums import Criticality
from app.services.risk_scenarios import (
    ACCEPTED,
    FITS,
    PENDING,
    REJECTED,
    AssetFacts,
    KeyOwner,
    Placement,
    ScenarioSpec,
    TitlePattern,
    candidate_title,
    dedupe_key,
    group_subject,
    group_title,
    kind_labels,
    match_generated_title,
    merge_refs,
    scenario_fit,
    scope_label,
    title_for,
    worst_scores,
)

#: ``changes.via`` on every activity-trail entry the migration writes.
MIGRATION_VIA = "legacy_migration"

#: Links the old generator itself wrote: they do not make a risk "worked on".
GENERATOR_LINKS = frozenset({"assets", "controls", "threats", "vulnerabilities", "requirements"})

#: Activity on a risk that means a person has worked on it, as the plan words it.
ACTIVITY_LABELS: dict[str, tuple[str, str]] = {
    "restored": ("it was restored from the archive", "it was restored from the archive"),
    "edits": ("1 change by a person in its activity trail", "{n} changes by people in its activity trail"),
    "treatment_actions": ("1 treatment action", "{n} treatment actions"),
    "acceptances": ("1 acceptance request", "{n} acceptance requests"),
    "impact_dimensions": ("impact scored by dimension", "impact scored by dimension"),
    "comments": ("1 comment", "{n} comments"),
    "attachments": ("1 attachment", "{n} attachments"),
    "attestations": ("1 attestation", "{n} attestations"),
    "approvals": ("1 approval request", "{n} approval requests"),
}

_STATUS_LABEL = {
    "assessed": "Assessed", "treatment_planned": "Treatment planned",
    "treatment_in_progress": "Treatment in progress", "accepted": "Accepted", "closed": "Closed",
}


# ------------------------------------------------------------------- the facts ---
@dataclass(frozen=True)
class LinkedAsset:
    id: uuid.UUID
    name: str
    deleted: bool = False


@dataclass(frozen=True)
class LegacyRisk:
    """What the plan needs to know about one register risk."""

    id: uuid.UUID
    reference: str
    title: str
    status: str = "draft"
    workflow_status: str = "draft"
    level: int | None = None
    parent_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    treatment_owner_id: uuid.UUID | None = None
    treatment_strategy: str | None = None
    assessment_rationale: str = ""
    residual_likelihood: int | None = None
    residual_impact: int | None = None
    target_likelihood: int | None = None
    target_impact: int | None = None
    inherent_likelihood: int | None = None
    inherent_impact: int | None = None
    assets: tuple[LinkedAsset, ...] = ()
    #: Live linked controls, and their references.
    control_ids: frozenset[uuid.UUID] = frozenset()
    control_refs: tuple[str, ...] = ()
    #: Live links by kind (``risk_integrity.LINK_KINDS``) beyond :data:`GENERATOR_LINKS`.
    other_links: Mapping[str, int] = field(default_factory=dict)
    #: Activity by kind (:data:`ACTIVITY_LABELS`).
    activity: Mapping[str, int] = field(default_factory=dict)
    #: A candidate was promoted to this risk, or already rebuilt from it.
    from_queue: bool = False


@dataclass(frozen=True)
class Recognition:
    scenario_reference: str
    #: The linked asset the title names; None when the title names an asset the risk
    #: does not link (``named`` says which).
    asset: LinkedAsset | None
    named: str


def recognise(
    risk: LegacyRisk,
    patterns: Sequence[TitlePattern],
    assets_by_name: Mapping[str, LinkedAsset],
) -> Recognition | None:
    """Whether the old generator wrote this risk, and for which scenario and asset.

    ``assets_by_name`` maps lower-cased names to register assets (live preferred) for
    the names the title could carry. Readings are tried in pattern order; a reading
    that names a linked asset wins. With no linked asset left, a reading naming an
    archived asset counts (its link went with it). A title naming an asset that exists
    but is not linked is a mismatch (``asset`` None). Anything else — a hand-written
    title that merely reads like a scenario — is not recognised.
    """
    hits = match_generated_title(risk.title, patterns)
    if not hits:
        return None
    linked = {a.name.strip().lower(): a for a in risk.assets if a.name.strip()}
    for reference, names in hits:
        for name in names:
            if name.strip().lower() in linked:
                return Recognition(reference, linked[name.strip().lower()], name.strip())
    for reference, names in hits:
        for name in names:
            known = assets_by_name.get(name.strip().lower())
            if known is None:
                continue
            if not risk.assets and known.deleted:
                return Recognition(reference, known, name.strip())
            if risk.assets:
                return Recognition(reference, None, known.name)
    return None


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def edit_reasons(risk: LegacyRisk, allowed_controls: Iterable[uuid.UUID] = ()) -> list[str]:
    """Why a recognised risk counts as worked on (empty = untouched). Pure.

    ``allowed_controls`` are those the generator would have linked: the asset's own live
    controls and the scenario's references resolved against the catalogue.
    """
    from app.services.risk_integrity import LINK_KINDS

    out: list[str] = []
    if len(risk.assets) > 1:
        out.append(f"it is linked to {len(risk.assets)} assets")
    if (risk.status or "draft") != "draft":
        out.append(f"its status is {_STATUS_LABEL.get(risk.status, risk.status)}")
    if (risk.workflow_status or "draft") != "draft":
        out.append("it has been through approval")
    if risk.parent_id is not None:
        out.append("it sits under a parent risk")
    if risk.owner_id is not None or risk.treatment_owner_id is not None:
        out.append("it has an owner")
    if risk.treatment_strategy:
        out.append("a treatment strategy was chosen")
    if (risk.assessment_rationale or "").strip():
        out.append("it has an assessment rationale")
    if risk.residual_likelihood is not None or risk.residual_impact is not None:
        out.append("residual scores were recorded")
    if risk.target_likelihood is not None or risk.target_impact is not None:
        out.append("target scores were recorded")
    extra = len(set(risk.control_ids) - set(allowed_controls))
    if extra:
        out.append(_count(extra, "1 control was linked by hand", "{n} controls were linked by hand"))
    labels = dict(LINK_KINDS)
    for kind, _label in LINK_KINDS:
        n = int(risk.other_links.get(kind, 0) or 0)
        if n and kind not in GENERATOR_LINKS:
            out.append(f"it is linked to {labels[kind].lower()} ({n})")
    for kind, (one, many) in ACTIVITY_LABELS.items():
        n = int(risk.activity.get(kind, 0) or 0)
        if n:
            out.append(_count(n, one, many))
    return out


# -------------------------------------------------------------------- the plan ---
@dataclass(frozen=True)
class Move:
    risk: LegacyRisk
    scenario_reference: str
    asset: LinkedAsset
    #: The title the scenario gives this asset alone.
    auto_title: str


@dataclass
class Group:
    """One candidate the moving risks become."""

    key: str
    spec: ScenarioSpec
    placement: Placement
    #: The pending candidate with this key, when there is one: the risks join it.
    joins: KeyOwner | None = None
    moves: list[Move] = field(default_factory=list)

    @property
    def asset_ids(self) -> list[uuid.UUID]:
        return list(dict.fromkeys(m.asset.id for m in self.moves))

    @property
    def scores(self) -> tuple[int | None, int | None]:
        return worst_scores((m.risk.inherent_likelihood, m.risk.inherent_impact) for m in self.moves)

    @property
    def refs(self) -> list[str]:
        return merge_refs(self.spec.control_references, *(m.risk.control_refs for m in self.moves))

    @property
    def group_title(self) -> str:
        return group_title(self.spec.title, group_subject(self.placement))

    @property
    def title(self) -> str:
        """A new candidate's title: the risk's own title for one asset, the group's for
        several (``candidate_title``)."""
        return candidate_title(
            [m.risk.title for m in self.moves],
            group=self.group_title,
            asset_count=len(self.asset_ids),
            single_asset_titles={m.auto_title.lower() for m in self.moves} | {m.risk.title.lower() for m in self.moves},
        )


@dataclass(frozen=True)
class Outcome:
    """A recognised risk that is dropped or kept, and why."""

    risk: LegacyRisk
    scenario_reference: str
    asset: LinkedAsset | None
    reason: str


@dataclass
class MigrationPlan:
    groups: list[Group] = field(default_factory=list)
    dropped: list[Outcome] = field(default_factory=list)
    kept: list[Outcome] = field(default_factory=list)

    @property
    def moving(self) -> int:
        return sum(len(g.moves) for g in self.groups)

    @property
    def recognised(self) -> int:
        return self.moving + len(self.dropped) + len(self.kept)

    @property
    def new_candidates(self) -> int:
        return sum(1 for g in self.groups if g.joins is None)

    @property
    def joined_candidates(self) -> int:
        return len({g.joins.proposal_id for g in self.groups if g.joins is not None})

    @property
    def to_archive(self) -> list[LegacyRisk]:
        return [m.risk for g in self.groups for m in g.moves] + [o.risk for o in self.dropped]

    def __bool__(self) -> bool:
        return bool(self.groups or self.dropped)


def placement_key(spec_reference: str, where: Placement) -> str:
    return dedupe_key(spec_reference, where.process_id, where.business_unit_id, where.asset_class)


def _is_for(labels: list[str]) -> str:
    return ", ".join(labels) if labels else "other kinds of asset"


def plan_migration(
    risks: Iterable[LegacyRisk],
    *,
    patterns: Sequence[TitlePattern],
    specs: Mapping[str, ScenarioSpec],
    assets_by_name: Mapping[str, LinkedAsset],
    facts: Mapping[uuid.UUID, AssetFacts],
    placements: Mapping[uuid.UUID, Placement],
    allowed_controls: Mapping[uuid.UUID, Iterable[uuid.UUID]],
    owners: Mapping[str, KeyOwner],
) -> MigrationPlan:
    """What happens to each risk (module docstring for the rules). Pure; risks are
    taken in reference order so groups, titles and ``source_risk_id`` are stable.

    ``specs`` are the organisation's scenarios by upper-cased reference; ``facts`` and
    ``placements`` are per asset; ``owners`` are what each key already has in the queue.
    """
    plan = MigrationPlan()
    groups: dict[str, Group] = {}
    for risk in sorted(risks, key=lambda r: ((r.reference or "").upper(), str(r.id))):
        if risk.from_queue or risk.level is not None:
            continue
        found = recognise(risk, patterns, assets_by_name)
        if found is None:
            continue
        reference = found.scenario_reference.strip().upper()
        spec = specs.get(reference)
        if spec is None:
            continue
        if found.asset is None:
            linked = ", ".join(f"“{a.name}”" for a in risk.assets)
            plan.kept.append(Outcome(
                risk, spec.reference, None,
                f"its title names “{found.named}” but it is linked to {linked}: correct the title or the link",
            ))
            continue
        reasons = edit_reasons(risk, allowed_controls.get(risk.id, ()))
        if reasons:
            plan.kept.append(Outcome(risk, spec.reference, found.asset, "; ".join(reasons)))
            continue
        asset = found.asset
        if asset.deleted:
            plan.dropped.append(Outcome(risk, spec.reference, asset, f"its asset “{asset.name}” was deleted"))
            continue
        asset_facts = facts.get(asset.id)
        if asset_facts is not None and scenario_fit(spec, asset_facts) != FITS:
            what = _is_for(kind_labels(asset_facts.kinds))
            plan.dropped.append(Outcome(
                risk, spec.reference, asset,
                f"{spec.reference} does not fit “{asset.name}” ({what}); "
                f"the scenario is for {_is_for(kind_labels(spec.asset_kinds)) if spec.asset_kinds else 'another class of asset'}",
            ))
            continue
        where = placements.get(asset.id) or Placement(asset_class=asset_facts.asset_class if asset_facts else "")
        key = placement_key(spec.reference, where)
        owner = owners.get(key)
        if owner is not None and owner.status == ACCEPTED:
            plan.kept.append(Outcome(
                risk, spec.reference, asset,
                f"{owner.risk_reference or 'a risk accepted from the queue'} already covers {spec.reference} for "
                f"{scope_label(where)}; archive this one by hand if it is a duplicate",
            ))
            continue
        if owner is not None and owner.status == REJECTED:
            note = f": {owner.note}" if owner.note else ""
            plan.dropped.append(Outcome(
                risk, spec.reference, asset,
                f"the candidate for {spec.reference} in {scope_label(where)} was rejected{note}",
            ))
            continue
        group = groups.get(key)
        if group is None:
            group = Group(key, spec, where, owner if owner is not None and owner.status == PENDING else None)
            groups[key] = group
            plan.groups.append(group)
        group.moves.append(Move(risk, spec.reference, asset, _auto_title(spec, asset.name)))
    return plan


def _auto_title(spec: ScenarioSpec, name: str) -> str:
    """The title the scenario gives one asset (only the name matters to ``title_for``)."""
    m = Criticality.medium
    return title_for(spec, AssetFacts(name, "", m, m, m, m, m))


# ------------------------------------------------------------------ the loaders ---
@dataclass
class Context:
    """What :func:`apply` needs beyond the plan."""

    templates: dict[str, object] = field(default_factory=dict)  # upper reference -> template row


async def load_plan(db) -> tuple[MigrationPlan, Context]:
    """Read everything the plan needs — a fixed number of queries — and plan."""
    from sqlalchemy import func, literal_column, select, union_all

    from app.api.v1 import risk_scenarios as api
    from app.models.approval import ApprovalRequest
    from app.models.asset import Asset
    from app.models.attestation import Attestation
    from app.models.audit import AuditLog
    from app.models.collab import Attachment, Comment, StoredFile
    from app.models.control import Control, control_assets
    from app.models.risk import (
        Risk,
        RiskAcceptance,
        RiskImpactDimension,
        RiskTreatmentAction,
        risk_assets,
        risk_controls,
    )
    from app.models.risk_scenario import RiskProposal, RiskScenarioTemplate
    from app.services import risk_integrity
    from app.services.risk_scenarios import title_patterns

    ctx = Context()
    templates = list((await db.scalars(select(RiskScenarioTemplate))).all())
    ctx.templates = {(t.reference or "").strip().upper(): t for t in templates}
    specs = {ref: api._spec(t) for ref, t in ctx.templates.items()}
    patterns = title_patterns((t.reference, t.title) for t in templates)
    if not patterns:
        return MigrationPlan(), ctx

    columns = (
        Risk.id, Risk.reference, Risk.title, Risk.status, Risk.workflow_status, Risk.level, Risk.parent_id,
        Risk.owner_id, Risk.treatment_owner_id, Risk.treatment_strategy, Risk.assessment_rationale,
        Risk.residual_likelihood, Risk.residual_impact, Risk.target_likelihood, Risk.target_impact,
        Risk.inherent_likelihood, Risk.inherent_impact,
    )
    rows = [
        r for r in (
            await db.execute(select(*columns).where(Risk.deleted.is_(False), Risk.level.is_(None)))
        ).all()
        if match_generated_title(r.title or "", patterns)
    ]
    if not rows:
        return MigrationPlan(), ctx
    ids = [r.id for r in rows]
    readings = {
        n.strip().lower()
        for r in rows for _ref, names in match_generated_title(r.title or "", patterns) for n in names if n.strip()
    }

    linked: dict[uuid.UUID, list[LinkedAsset]] = {}
    for rid, aid, name, deleted in (
        await db.execute(
            select(risk_assets.c.risk_id, Asset.id, Asset.name, Asset.deleted)
            .join(Asset, Asset.id == risk_assets.c.asset_id)
            .where(risk_assets.c.risk_id.in_(ids))
        )
    ).all():
        linked.setdefault(rid, []).append(LinkedAsset(aid, name or "", bool(deleted)))
    assets_by_name: dict[str, LinkedAsset] = {}
    for aid, name, deleted in (
        await db.execute(
            select(Asset.id, Asset.name, Asset.deleted)
            .where(func.lower(func.trim(Asset.name)).in_(sorted(readings)))
            .order_by(Asset.deleted, Asset.created_at)
        )
    ).all():
        assets_by_name.setdefault((name or "").strip().lower(), LinkedAsset(aid, (name or "").strip(), bool(deleted)))

    from_queue = set(
        (await db.scalars(select(RiskProposal.promoted_risk_id).where(RiskProposal.promoted_risk_id.in_(ids)))).all()
    ) | set(
        (await db.scalars(select(RiskProposal.source_risk_id).where(RiskProposal.source_risk_id.in_(ids)))).all()
    )

    controls: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for rid, cid, ref in (
        await db.execute(
            select(risk_controls.c.risk_id, Control.id, Control.reference)
            .join(Control, Control.id == risk_controls.c.control_id)
            .where(risk_controls.c.risk_id.in_(ids), Control.deleted.is_(False))
            .order_by(Control.reference)
        )
    ).all():
        controls.setdefault(rid, []).append((cid, ref or ""))

    links = await risk_integrity.live_link_counts(db, ids)

    def kind(name: str):
        return literal_column(f"'{name}'").label("kind")

    def by_risk(name: str, column, *where):
        return select(kind(name), column.label("risk_id"), func.count().label("n")).where(
            column.in_(ids), *where
        ).group_by(column)

    activity: dict[uuid.UUID, dict[str, int]] = {}
    person = AuditLog.actor_id.is_not(None)
    parts = [
        by_risk("restored", AuditLog.entity_id, AuditLog.entity_type == "risk", person, AuditLog.action == "restore"),
        by_risk("edits", AuditLog.entity_id, AuditLog.entity_type == "risk", person,
                AuditLog.action.notin_(("create", "restore"))),
        by_risk("treatment_actions", RiskTreatmentAction.risk_id),
        by_risk("acceptances", RiskAcceptance.risk_id),
        by_risk("impact_dimensions", RiskImpactDimension.risk_id),
        by_risk("comments", Comment.entity_id, Comment.entity_type == "risk"),
        by_risk("attachments", Attachment.entity_id, Attachment.entity_type == "risk"),
        by_risk("attachments", StoredFile.entity_id, StoredFile.entity_type == "risk"),
        by_risk("attestations", Attestation.entity_id, Attestation.entity_type == "risk"),
        by_risk("approvals", ApprovalRequest.entity_id, ApprovalRequest.entity_type == "risk"),
    ]
    for name, rid, n in (await db.execute(union_all(*parts))).all():
        counts = activity.setdefault(rid, {})
        counts[name] = counts.get(name, 0) + int(n)

    asset_ids = {a.id for assets in linked.values() for a in assets} | {a.id for a in assets_by_name.values()}
    asset_rows = list((await db.scalars(select(Asset).where(Asset.id.in_(list(asset_ids))))).all()) if asset_ids else []
    facts = {a.id: api._facts(a) for a in asset_rows}
    live_ids = [a.id for a in asset_rows if not a.deleted]
    placements = await api._placements(db, live_ids)

    asset_controls: dict[uuid.UUID, set[uuid.UUID]] = {}
    if live_ids:
        for aid, cid in (
            await db.execute(
                select(control_assets.c.asset_id, Control.id)
                .join(Control, Control.id == control_assets.c.control_id)
                .where(control_assets.c.asset_id.in_(live_ids), Control.deleted.is_(False))
            )
        ).all():
            asset_controls.setdefault(aid, set()).add(cid)
    wanted_refs = {ref.lower() for spec in specs.values() for ref in spec.control_references}
    catalogue: dict[str, set[uuid.UUID]] = {}
    if wanted_refs:
        for cid, ref in (
            await db.execute(
                select(Control.id, Control.reference)
                .where(func.lower(Control.reference).in_(sorted(wanted_refs)), Control.deleted.is_(False))
            )
        ).all():
            catalogue.setdefault((ref or "").strip().lower(), set()).add(cid)

    risks: list[LegacyRisk] = []
    allowed: dict[uuid.UUID, set[uuid.UUID]] = {}
    keys: set[str] = set()
    for r in rows:
        risk = LegacyRisk(
            id=r.id, reference=r.reference or "", title=r.title or "",
            status=_value(r.status) or "draft", workflow_status=_value(r.workflow_status) or "draft",
            level=r.level, parent_id=r.parent_id, owner_id=r.owner_id, treatment_owner_id=r.treatment_owner_id,
            treatment_strategy=_value(r.treatment_strategy) or None,
            assessment_rationale=r.assessment_rationale or "",
            residual_likelihood=r.residual_likelihood, residual_impact=r.residual_impact,
            target_likelihood=r.target_likelihood, target_impact=r.target_impact,
            inherent_likelihood=r.inherent_likelihood, inherent_impact=r.inherent_impact,
            assets=tuple(linked.get(r.id, ())),
            control_ids=frozenset(c for c, _ in controls.get(r.id, ())),
            control_refs=tuple(ref for _, ref in controls.get(r.id, ()) if ref),
            other_links={k: v for k, v in links.get(r.id, {}).items() if v and k not in GENERATOR_LINKS},
            activity=activity.get(r.id, {}),
            from_queue=r.id in from_queue,
        )
        risks.append(risk)
        found = recognise(risk, patterns, assets_by_name)
        if found is None or found.asset is None:
            continue
        spec = specs.get(found.scenario_reference.strip().upper())
        if spec is None:
            continue
        allowed[risk.id] = set(asset_controls.get(found.asset.id, set())) | {
            cid for ref in spec.control_references for cid in catalogue.get(ref.lower(), set())
        }
        where = placements.get(found.asset.id)
        if where is not None:
            keys.add(placement_key(spec.reference, where))

    owners = await api._key_owners(db, keys)
    plan = plan_migration(
        risks, patterns=patterns, specs=specs, assets_by_name=assets_by_name, facts=facts,
        placements=placements, allowed_controls=allowed, owners=owners,
    )
    return plan, ctx


def _value(value) -> str:
    return getattr(value, "value", value) or ""


def plan_read(plan: MigrationPlan):
    """The plan as the API returns it (``schemas.risk_scenario.LegacyMigrationPlan``)."""
    from app.schemas.risk_scenario import LegacyGroupRead, LegacyMigrationPlan, LegacyRiskRef

    def ref(risk: LegacyRisk, scenario: str, asset: LinkedAsset | None, reason: str = "") -> LegacyRiskRef:
        return LegacyRiskRef(
            id=risk.id, reference=risk.reference, title=risk.title, scenario_reference=scenario,
            asset_id=asset.id if asset else None, asset_name=asset.name if asset else "",
            inherent_likelihood=risk.inherent_likelihood, inherent_impact=risk.inherent_impact, reason=reason,
        )

    groups = []
    for g in plan.groups:
        likelihood, impact = g.scores
        groups.append(LegacyGroupRead(
            dedupe_key=g.key, scenario_reference=g.spec.reference,
            scenario_title=g.spec.title.replace("{asset}", "…"),
            title=g.joins.title if g.joins is not None else g.title,
            scope_label=scope_label(g.placement), inherent_likelihood=likelihood, inherent_impact=impact,
            control_references=g.refs,
            joins_proposal_id=g.joins.proposal_id if g.joins is not None else None,
            joins_title=g.joins.title if g.joins is not None else "",
            risks=[ref(m.risk, m.scenario_reference, m.asset) for m in g.moves],
        ))
    return LegacyMigrationPlan(
        recognised=plan.recognised, moving=plan.moving, dropped=len(plan.dropped), kept=len(plan.kept),
        new_candidates=plan.new_candidates, joined_candidates=plan.joined_candidates, groups=groups,
        dropped_items=[ref(o.risk, o.scenario_reference, o.asset, o.reason) for o in plan.dropped],
        kept_items=[ref(o.risk, o.scenario_reference, o.asset, o.reason) for o in plan.kept],
    )


# -------------------------------------------------------------------- apply ---
async def apply(db, user):
    """Carry out the plan as it stands now (it is re-read under the queue lock, so a
    preview that went stale cannot move the wrong risks). Returns
    ``schemas.risk_scenario.LegacyMigrationResult``."""
    from sqlalchemy import select

    from app.api.v1 import risk_scenarios as api
    from app.models.risk import Risk
    from app.models.risk_scenario import RiskProposal
    from app.schemas.risk_scenario import LegacyMigrationResult
    from app.services import audit as audit_log
    from app.services.risk_scenarios import split_refs

    await api._lock_queue(db, user.tenant_id)
    plan, ctx = await load_plan(db)
    if not plan:
        return LegacyMigrationResult(archived=0, moved=0, dropped=0, kept=len(plan.kept), created=0, joined=0)

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    categories = await api._category_ids(db, (g.spec.category for g in plan.groups))
    links: list[dict] = []
    proposal_of: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}  # risk id -> (candidate id, title)

    created: list[tuple[RiskProposal, Group]] = []
    for group in plan.groups:
        if group.joins is not None:
            continue
        likelihood, impact = group.scores
        row = RiskProposal(
            tenant_id=user.tenant_id, run_id=run_id, scenario_reference=group.spec.reference,
            title=group.title, description=(group.spec.description or "").strip(),
            business_unit_id=group.placement.business_unit_id, process_id=group.placement.process_id,
            category_id=categories.get((group.spec.category or "").strip().lower()),
            inherent_likelihood=likelihood, inherent_impact=impact,
            control_references=", ".join(group.refs), dedupe_key=group.key, status=PENDING,
            created_by_id=user.id, decision_note="", source_risk_id=group.moves[0].risk.id,
        )
        db.add(row)
        created.append((row, group))
    if created:
        await db.flush()
    for row, group in created:
        links.extend({"proposal_id": row.id, "asset_id": aid} for aid in group.asset_ids)
        for move in group.moves:
            proposal_of[move.risk.id] = (row.id, row.title)

    joining = [g for g in plan.groups if g.joins is not None]
    joined_ids: list[uuid.UUID] = []
    if joining:
        existing = {
            r.id: r
            for r in (
                await db.scalars(
                    select(RiskProposal)
                    .where(RiskProposal.id.in_([g.joins.proposal_id for g in joining]))
                    .with_for_update()
                )
            ).all()
        }
        current = await api._asset_ids_by_proposal(db, list(existing), live_only=False)
        names = await api._asset_names(db, {aid for ids in current.values() for aid in ids})
        for group in joining:
            row = existing.get(group.joins.proposal_id)
            if row is None or row.status != PENDING:
                # Decided since the owners were read: leave these risks for the next run.
                continue
            held = current.get(row.id, [])
            added = [aid for aid in group.asset_ids if aid not in set(held)]
            before = (row.inherent_likelihood, row.inherent_impact, row.title)
            row.inherent_likelihood, row.inherent_impact = worst_scores([
                (row.inherent_likelihood, row.inherent_impact), group.scores,
            ])
            row.control_references = ", ".join(merge_refs(split_refs(row.control_references), group.refs))
            template = ctx.templates.get((row.scenario_reference or "").strip().upper())
            single = {m.auto_title.lower() for m in group.moves} | {m.risk.title.lower() for m in group.moves}
            if template is not None:
                single |= {api._auto_title(template, names[a]).lower() for a in held if a in names}
            row.title = candidate_title(
                [row.title], group=group.group_title, asset_count=len({*held, *group.asset_ids}),
                single_asset_titles=single,
            )
            if row.source_risk_id is None:
                row.source_risk_id = group.moves[0].risk.id
            current[row.id] = [*held, *added]
            links.extend({"proposal_id": row.id, "asset_id": aid} for aid in added)
            joined_ids.append(row.id)
            for move in group.moves:
                proposal_of[move.risk.id] = (row.id, row.title)
            await audit_log.record(
                db, actor=user, action="update", entity_type="risk_proposal", entity_id=row.id,
                summary=(
                    f"Added {len(group.moves)} register risk(s) made before the candidate queue to "
                    f"“{row.title}”: {', '.join(m.risk.reference for m in group.moves)}"
                )[:500],
                changes={
                    "via": MIGRATION_VIA, "run_id": str(run_id), "assets_added": len(added),
                    "source_risks": ", ".join(m.risk.reference for m in group.moves),
                    **({"scores": f"{before[0]}x{before[1]} -> {row.inherent_likelihood}x{row.inherent_impact}"}
                       if (before[0], before[1]) != (row.inherent_likelihood, row.inherent_impact) else {}),
                    **({"title": f"{before[2]} -> {row.title}"} if before[2] != row.title else {}),
                },
            )
    await api._link_assets(db, links)

    dropped_reason = {o.risk.id: o.reason for o in plan.dropped}
    archive_ids = [rid for rid in proposal_of] + list(dropped_reason)
    risks = {
        r.id: r for r in (await db.scalars(select(Risk).where(Risk.id.in_(archive_ids), Risk.deleted.is_(False)))).all()
    }
    moved = dropped = 0
    for rid in archive_ids:
        risk = risks.get(rid)
        if risk is None:
            continue
        risk.deleted = True
        risk.deleted_date = now
        if rid in proposal_of:
            moved += 1
        else:
            dropped += 1
    await db.flush()
    for rid in archive_ids:
        risk = risks.get(rid)
        if risk is None:
            continue
        if rid in proposal_of:
            pid, title = proposal_of[rid]
            summary = f"Archived risk {risk.reference}: moved to risk candidates as “{title}”"
            changes = {"via": MIGRATION_VIA, "run_id": str(run_id), "proposal_id": str(pid)}
        else:
            summary = (
                f"Archived risk {risk.reference}: generated before the candidate queue and not moved to it — "
                f"{dropped_reason[rid]}"
            )
            changes = {"via": MIGRATION_VIA, "run_id": str(run_id), "dropped": dropped_reason[rid]}
        await audit_log.record(
            db, actor=user, action="delete", entity_type="risk", entity_id=risk.id,
            summary=summary[:500], changes=changes,
        )
    for row, group in created:
        await audit_log.record(
            db, actor=user, action="create", entity_type="risk_proposal", entity_id=row.id,
            summary=(
                f"Created risk candidate “{row.title}” from register risk(s) made before the candidate queue: "
                f"{', '.join(m.risk.reference for m in group.moves)}"
            )[:500],
            changes={
                "via": MIGRATION_VIA, "run_id": str(run_id), "assets": len(group.asset_ids),
                "source_risks": ", ".join(m.risk.reference for m in group.moves),
            },
        )
    await audit_log.record(
        db, actor=user, action=MIGRATION_VIA, entity_type="risk_proposal", entity_id=None,
        summary=(
            f"Moved {moved} generated risk(s) made before the candidate queue into {len(created)} new and "
            f"{len(joined_ids)} waiting candidate(s); archived {dropped} more that do not fit; "
            f"kept {len(plan.kept)} that people have worked on"
        ),
        changes={
            "run_id": str(run_id), "moved": moved, "dropped": dropped, "kept": len(plan.kept),
            "created": len(created), "joined": len(joined_ids),
        },
    )
    return LegacyMigrationResult(
        archived=moved + dropped, moved=moved, dropped=dropped, kept=len(plan.kept),
        created=len(created), joined=len(joined_ids),
        proposals=list(dict.fromkeys([r.id for r, _ in created] + joined_ids)),
    )


# ------------------------------------------------------------ restore (phase 4) ---
RESTORED_NOTE = "Source risk restored"
WITHDRAW, TRIM = "withdraw", "trim"


@dataclass(frozen=True)
class RestoreOutcome:
    """What restoring one moved risk does to one pending candidate."""

    action: str | None  # WITHDRAW, TRIM or None (nothing to do)
    remove_assets: frozenset[uuid.UUID] = frozenset()


def restore_outcome(
    *,
    restored_id: uuid.UUID,
    created_by_migration: bool,
    sources: Iterable[uuid.UUID],
    live_sources: Iterable[uuid.UUID],
    assets_by_source: Mapping[uuid.UUID, Iterable[uuid.UUID]],
    candidate_assets: Iterable[uuid.UUID],
) -> RestoreOutcome:
    """Decide for one *pending* candidate. Pure.

    ``sources`` are the risks the migration moved into the candidate, ``live_sources``
    those live now (the restored one included). Withdraw when the migration made the
    candidate and every source is back; else remove the restored risk's assets that no
    still-archived source carries; withdraw when that leaves the candidate empty."""
    sources = set(sources) | {restored_id}
    archived = sources - set(live_sources) - {restored_id}
    if created_by_migration and not archived:
        return RestoreOutcome(WITHDRAW)
    kept = {a for sid in archived for a in assets_by_source.get(sid, ())}
    held = set(candidate_assets)
    remove = (set(assets_by_source.get(restored_id, ())) & held) - kept
    if held and not (held - remove):
        return RestoreOutcome(WITHDRAW, frozenset(remove))
    return RestoreOutcome(TRIM if remove else None, frozenset(remove))


async def release_on_restore(db, user, risk) -> str:
    """Withdraw or trim the pending candidates ``risk`` was moved into (see
    :func:`restore_outcome`); audited on each candidate. Returns a sentence for the
    restore's own audit entry and reply ("" when the risk was never moved)."""
    from sqlalchemy import delete, or_, select

    from app.models.audit import AuditLog
    from app.models.risk import Risk, risk_assets
    from app.models.risk_scenario import RiskProposal, risk_proposal_assets
    from app.services import audit as audit_log

    moved = (AuditLog.entity_type == "risk") & (AuditLog.action == "delete") & (
        AuditLog.changes["via"].astext == MIGRATION_VIA
    )
    named = {
        uuid.UUID(pid)
        for pid in (
            await db.scalars(
                select(AuditLog.changes["proposal_id"].astext).where(moved, AuditLog.entity_id == risk.id)
            )
        ).all()
        if pid
    }
    proposals = (
        await db.scalars(
            select(RiskProposal)
            .where(
                or_(RiskProposal.id.in_(named), RiskProposal.source_risk_id == risk.id) if named
                else RiskProposal.source_risk_id == risk.id,
                RiskProposal.status == PENDING,
            )
            .with_for_update()
        )
    ).all()
    if not proposals:
        return ""
    now = datetime.now(timezone.utc)
    notes: list[str] = []
    for proposal in proposals:
        pid = str(proposal.id)
        sources = set(
            (await db.scalars(select(AuditLog.entity_id).where(moved, AuditLog.changes["proposal_id"].astext == pid))).all()
        ) - {None}
        if proposal.source_risk_id is not None:
            sources.add(proposal.source_risk_id)
        sources.add(risk.id)
        live = set((await db.scalars(select(Risk.id).where(Risk.id.in_(sources), Risk.deleted.is_(False)))).all())
        live.add(risk.id)
        created = await db.scalar(
            select(AuditLog.id).where(
                AuditLog.entity_type == "risk_proposal", AuditLog.entity_id == proposal.id,
                AuditLog.action == "create", AuditLog.changes["via"].astext == MIGRATION_VIA,
            ).limit(1)
        )
        by_source: dict[uuid.UUID, set[uuid.UUID]] = {}
        for rid, aid in (
            await db.execute(select(risk_assets.c.risk_id, risk_assets.c.asset_id).where(risk_assets.c.risk_id.in_(sources)))
        ).all():
            by_source.setdefault(rid, set()).add(aid)
        held = set(
            (await db.scalars(
                select(risk_proposal_assets.c.asset_id).where(risk_proposal_assets.c.proposal_id == proposal.id)
            )).all()
        )
        outcome = restore_outcome(
            restored_id=risk.id, created_by_migration=created is not None, sources=sources,
            live_sources=live, assets_by_source=by_source, candidate_assets=held,
        )
        if outcome.action is None:
            continue
        if outcome.remove_assets:
            await db.execute(
                delete(risk_proposal_assets).where(
                    risk_proposal_assets.c.proposal_id == proposal.id,
                    risk_proposal_assets.c.asset_id.in_(list(outcome.remove_assets)),
                )
            )
        if outcome.action == WITHDRAW:
            proposal.status = REJECTED
            proposal.decided_by_id = user.id
            proposal.decided_at = now
            proposal.decision_note = RESTORED_NOTE
            summary = (
                f"Withdrew risk candidate “{proposal.title}”: its source risk {risk.reference} was restored "
                "to the register"
            )
            notes.append(f"withdrew risk candidate “{proposal.title}”")
        else:
            archived = sorted(sources - live)
            if proposal.source_risk_id == risk.id and archived:
                proposal.source_risk_id = archived[0]
            line = (
                f"{risk.reference} was restored to the register on {now.date().isoformat()}; "
                f"{len(outcome.remove_assets)} of its asset(s) left this candidate."
            )
            proposal.description = f"{proposal.description.rstrip()}\n\n{line}".strip()
            summary = (
                f"Removed {len(outcome.remove_assets)} asset(s) from risk candidate “{proposal.title}”: "
                f"its source risk {risk.reference} was restored to the register"
            )
            notes.append(f"removed its asset(s) from risk candidate “{proposal.title}”")
        await db.flush()
        await audit_log.record(
            db, actor=user, action="reject" if outcome.action == WITHDRAW else "update",
            entity_type="risk_proposal", entity_id=proposal.id, summary=summary[:500],
            changes={
                "via": "restore", "restored_risk": risk.reference, "outcome": outcome.action,
                "assets_removed": len(outcome.remove_assets),
            },
        )
    return "; ".join(notes)


__all__ = [
    "GENERATOR_LINKS",
    "MIGRATION_VIA",
    "RESTORED_NOTE",
    "RestoreOutcome",
    "release_on_restore",
    "restore_outcome",
    "Group",
    "LegacyRisk",
    "LinkedAsset",
    "MigrationPlan",
    "Move",
    "Outcome",
    "apply",
    "edit_reasons",
    "load_plan",
    "plan_migration",
    "plan_read",
    "recognise",
]
