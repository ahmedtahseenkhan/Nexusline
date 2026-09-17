"""Questionnaire versions: building a draft's tree, publishing, new versions and
installing shipped templates (product review phase 4E).

Rules:

* Only a **draft** version can be edited. Saving replaces the draft's whole section /
  question / option tree (no assessment can point at a draft, so nothing is lost).
* **Publishing** checks the structure (``questionnaire_logic.structure_problems``), the
  bands, and purpose-specific needs (due diligence needs bands; tiering needs choice
  questions only), stamps who and when, and marks the family's previously published
  version ``superseded``. A published version is never changed again; its assessments
  stay pinned to it.
* **New version**: copies the latest version (keys and option values unchanged, so
  conditions keep working) into the next-numbered draft. A family has at most one draft.
* **Install from the library**: a new family whose version 1 is a draft copy of the
  template, marked ``origin = library`` with the template key and version.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.models.assessment import (
    VERSION_DRAFT,
    VERSION_PUBLISHED,
    VERSION_SUPERSEDED,
    Assessment,
    Question,
    QuestionnaireSection,
    QuestionOption,
    Questionnaire,
)
from app.services import questionnaire_logic as ql


class VersionError(ValueError):
    """A version operation that is refused (the API answers 409 or 422)."""

    def __init__(self, message: str, *, status: int = 422, problems: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


# ================================================================ tree building ===
def _unique(base: str, taken: set[str], limit: int = 64) -> str:
    base = (base or "x")[: limit - 4]
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    taken.add(candidate)
    return candidate


def normalise_tree(sections: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fill blank section keys, question keys and option values (from the title, text and
    label), keeping any given. Pure. Given keys are kept as sent so conditions that
    refer to them still resolve; duplicates are reported by ``structure_problems``."""
    out: list[dict[str, Any]] = []
    section_keys: set[str] = {str(s.get("key")) for s in sections if s.get("key")}
    question_keys: set[str] = {str(q.get("key")) for s in sections for q in s.get("questions") or [] if q.get("key")}
    for s in sections:
        skey = str(s.get("key") or "") or _unique(ql.slug(str(s.get("title") or ""), "section"), section_keys)
        questions = []
        for q in s.get("questions") or []:
            qkey = str(q.get("key") or "") or _unique(ql.slug(str(q.get("text") or ""), "q")[:40], question_keys)
            values: set[str] = {str(o.get("value")) for o in q.get("options") or [] if o.get("value")}
            options = []
            for o in q.get("options") or []:
                value = str(o.get("value") or "") or _unique(ql.slug(str(o.get("label") or ""), "option")[:40], values)
                options.append({**dict(o), "value": value})
            questions.append({**dict(q), "key": qkey, "options": options})
        out.append({**dict(s), "key": skey, "questions": questions})
    return out


def build_rows(tenant_id: uuid.UUID, version_id: uuid.UUID, sections: Sequence[Mapping[str, Any]]) -> tuple[list[QuestionnaireSection], list[Question]]:
    """ORM rows for a normalised tree (ids assigned here so questions can name their section)."""
    section_rows: list[QuestionnaireSection] = []
    question_rows: list[Question] = []
    order = 0
    for si, s in enumerate(sections):
        section = QuestionnaireSection(
            id=uuid.uuid4(), tenant_id=tenant_id, questionnaire_id=version_id, key=str(s["key"]),
            title=str(s.get("title") or "").strip() or f"Section {si + 1}",
            description=str(s.get("description") or ""), order_index=si,
            conditions=dict(s.get("conditions") or {}),
        )
        section_rows.append(section)
        for q in s.get("questions") or []:
            qtype = q.get("type") or "single_choice"
            question = Question(
                id=uuid.uuid4(), tenant_id=tenant_id, questionnaire_id=version_id, section_id=section.id,
                key=str(q["key"]), text=str(q.get("text") or "").strip(), guidance=str(q.get("guidance") or ""),
                order_index=order, qtype=qtype, mandatory=bool(q.get("mandatory")),
                weight=float(1 if q.get("weight") is None else q.get("weight")),
                conditions=dict(q.get("conditions") or {}), config=dict(q.get("config") or {}),
            )
            order += 1
            question.options = [
                QuestionOption(
                    tenant_id=tenant_id, label=str(o.get("label") or "").strip(), score=float(o.get("score") or 0),
                    order_index=oi, value=str(o["value"]), is_na=bool(o.get("is_na")),
                    risk_flag=bool(o.get("risk_flag")), finding_title=str(o.get("finding_title") or "")[:255],
                    finding_severity=str(o.get("finding_severity") or "medium"),
                )
                for oi, o in enumerate(q.get("options") or [])
            ] if qtype in ql.CHOICE_TYPES else []
            question_rows.append(question)
    return section_rows, question_rows


def tree_from_payload(sections: Iterable[Any] | None, questions: Iterable[Any] | None) -> list[dict[str, Any]] | None:
    """The builder payload (pydantic models or dicts) as a plain tree; the legacy flat
    question list becomes one "Questions" section. None when neither was sent."""
    def plain(item: Any) -> dict[str, Any]:
        return item.model_dump() if hasattr(item, "model_dump") else dict(item)

    if sections is not None:
        return [plain(s) for s in sections]
    if questions is not None:
        qs = [plain(q) for q in questions]
        return [{"key": "questions", "title": "Questions", "description": "", "conditions": {}, "questions": qs}] if qs else []
    return None


def tree_problems(tree: Sequence[Mapping[str, Any]], *, for_publish: bool = False) -> list[str]:
    return ql.structure_problems(tree, for_publish=for_publish)


async def replace_tree(db, version: Questionnaire, tree: Sequence[Mapping[str, Any]]) -> None:
    """Replace a draft's sections and questions with ``tree`` (already normalised)."""
    if not version.is_editable:
        raise VersionError(
            f"Version {version.version} of '{version.name}' is published and can't be changed. "
            "Create a new version to edit it.", status=409,
        )
    for q in list(version.questions or []):
        await db.delete(q)
    await db.flush()
    for s in list(version.sections or []):
        await db.delete(s)
    await db.flush()
    sections, questions = build_rows(version.tenant_id, version.id, tree)
    for row in (*sections, *questions):
        db.add(row)
    await db.flush()


# ==================================================================== versions ===
async def family_versions(db, family_id: uuid.UUID) -> list[Questionnaire]:
    return list((await db.scalars(
        select(Questionnaire).where(Questionnaire.family_id == family_id).order_by(Questionnaire.version.desc())
    )).all())


async def published_version(db, family_id: uuid.UUID | None) -> Questionnaire | None:
    """The family's current published version (the one new assessments use)."""
    if family_id is None:
        return None
    return await db.scalar(
        select(Questionnaire)
        .where(Questionnaire.family_id == family_id, Questionnaire.status == VERSION_PUBLISHED)
        .order_by(Questionnaire.version.desc())
        .limit(1)
    )


async def usage_counts(db, version_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not version_ids:
        return {}
    rows = (await db.execute(
        select(Assessment.questionnaire_id, func.count())
        .where(Assessment.questionnaire_id.in_(list(version_ids)))
        .group_by(Assessment.questionnaire_id)
    )).all()
    return {qid: n for qid, n in rows}


def publish_problems(version: Any, tree: Sequence[Mapping[str, Any]]) -> list[str]:
    """Everything that stops a draft being published. Pure."""
    problems = ql.structure_problems(tree, for_publish=True)
    problems += ql.band_problems(getattr(version, "bands", None) or [])
    purpose = getattr(version, "purpose", "general") or "general"
    if purpose not in ql.PURPOSES:
        problems.append(f"Unknown purpose '{purpose}'.")
    if purpose in ("vendor_due_diligence", "rcsa_control_self_assessment") and not (getattr(version, "bands", None) or []):
        problems.append("Add scoring bands: the band of a reviewed assessment sets the rating.")
    if purpose == "vendor_tiering":
        others = [q for s in tree for q in s.get("questions") or [] if q.get("type") not in ("single_choice", "yes_no_na")]
        if others:
            problems.append("A tiering questionnaire can only have single-choice or yes/no questions (the tier reads each answer's score).")
    if purpose == "rcsa_control_self_assessment":
        roles = {(q.get("config") or {}).get("rcsa_role") for s in tree for q in s.get("questions") or []}
        if not {"design", "operation"} & roles:
            problems.append("Mark at least one question as the design or operation rating (config.rcsa_role) so the RCSA line can be rated.")
    return problems


async def publish(db, version: Questionnaire, user: Any, change_note: str = "") -> Questionnaire:
    if version.status != VERSION_DRAFT:
        raise VersionError(f"Version {version.version} is already {version.status}.", status=409)
    tree = ql.spec_from_version(version)
    problems = publish_problems(version, tree)
    if problems:
        raise VersionError("This version can't be published yet.", problems=problems)
    for other in await family_versions(db, version.family_id or version.id):
        if other.id != version.id and other.status == VERSION_PUBLISHED:
            other.status = VERSION_SUPERSEDED
    version.status = VERSION_PUBLISHED
    version.published_at = datetime.now(timezone.utc)
    version.published_by_id = getattr(user, "id", None)
    if change_note:
        version.change_note = change_note
    await db.flush()
    return version


def _clone_tree(version: Questionnaire) -> list[dict[str, Any]]:
    tree = ql.spec_from_version(version)
    guidance = {q.id: q.guidance or "" for q in version.questions or []}
    for s in tree:
        for q in s["questions"]:
            q["guidance"] = guidance.get(q.get("id"), "")
    return tree


async def new_version(db, source: Questionnaire, user: Any) -> tuple[Questionnaire, bool]:
    """The family's open draft, or a new draft copied from ``source``. Returns
    ``(draft, created)``."""
    family = source.family_id or source.id
    versions = await family_versions(db, family)
    draft = next((v for v in versions if v.status == VERSION_DRAFT), None)
    if draft is not None:
        return draft, False
    number = max([v.version for v in versions] + [source.version or 1]) + 1
    copy = Questionnaire(
        id=uuid.uuid4(), tenant_id=source.tenant_id, family_id=family, version=number, status=VERSION_DRAFT,
        name=source.name, description=source.description or "", purpose=source.purpose or "general",
        bands=list(source.bands or []), change_note="", origin=source.origin or "tenant",
        library_key=source.library_key or "", library_version=source.library_version,
    )
    db.add(copy)
    await db.flush()
    sections, questions = build_rows(source.tenant_id, copy.id, _clone_tree(source))
    for row in (*sections, *questions):
        db.add(row)
    await db.flush()
    return copy, True


async def create_family(
    db, *, tenant_id: uuid.UUID, name: str, description: str = "", purpose: str = "general",
    bands: list | None = None, tree: Sequence[Mapping[str, Any]] = (), origin: str = "tenant",
    library_key: str = "", library_version: int | None = None, status: str = VERSION_DRAFT,
    change_note: str = "",
) -> Questionnaire:
    qid = uuid.uuid4()
    q = Questionnaire(
        id=qid, tenant_id=tenant_id, family_id=qid, version=1, status=status, name=name,
        description=description, purpose=purpose, bands=list(bands or []), origin=origin,
        library_key=library_key, library_version=library_version, change_note=change_note,
    )
    db.add(q)
    await db.flush()
    sections, questions = build_rows(tenant_id, qid, normalise_tree(tree))
    for row in (*sections, *questions):
        db.add(row)
    await db.flush()
    return q


async def install_template(db, *, tenant_id: uuid.UUID, template: Mapping[str, Any], name: str | None = None) -> Questionnaire:
    taken = {(n or "").strip().lower() for n in (await db.scalars(select(Questionnaire.name))).all()}
    base = (name or template["name"]).strip()
    final, n = base, 2
    while final.lower() in taken:
        final = f"{base} ({n})"
        n += 1
    return await create_family(
        db, tenant_id=tenant_id, name=final, description=template["description"], purpose=template["purpose"],
        bands=template["bands"], tree=template["sections"], origin="library", library_key=template["key"],
        library_version=template["version"],
        change_note=f"Installed from the template library ({template['name']}, version {template['version']}).",
    )
