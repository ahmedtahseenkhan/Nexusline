"""Questionnaires and assessments API (product review phase 4E).

* **Questionnaire versions** — list (one row per questionnaire), create, save a draft
  (the whole tree), validate, preview a score, publish, open a new version, version
  history, delete. A published version is immutable (409 on edit).
* **Template library** — shipped templates; installing one makes a draft copy.
* **Assessments** — create (pins the questionnaire's published version), send (portal
  link + e-mail), links (issue, revoke, resend) and the access log, answers (in-app),
  submit, per-answer review, return to the respondent, final review (maker-checker),
  findings and raising a finding to an Issue.
* **RCSA** — run an RCSA as a control self-assessment questionnaire.
* **Respondent portal** (``/respond/{token}``, no session) — view, save, upload evidence,
  submit. See ``services/questionnaire_portal.py`` for the token, limits and logging.

Workflow rules: ``services/questionnaire_workflow.py``; scoring and conditions:
``services/questionnaire_logic.py``; versions: ``services/questionnaire_versions.py``.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.models.assessment import (
    REVIEW_ACCEPTED,
    REVIEW_PENDING,
    REVIEW_RETURNED,
    VERSION_DRAFT,
    VERSION_PUBLISHED,
    VERSION_SUPERSEDED,
    Assessment,
    AssessmentAccessLog,
    AssessmentAnswer,
    AssessmentFinding,
    AssessmentLink,
    Questionnaire,
)
from app.models.enums import FindingStatus, VendorAssessmentStatus
from app.models.vendor import Vendor
from app.schemas.assessment import (
    AccessLogRead,
    AnswerReview,
    AssessmentCreate,
    AssessmentRead,
    AssessmentReviewRequest,
    AssessmentSummary,
    AssessmentUpdate,
    FileRef,
    FindingCreate,
    FindingUpdate,
    LibraryInstall,
    LibraryTemplate,
    LinkCreate,
    LinkIssued,
    LinkRead,
    PortalAnswer,
    PortalOption,
    PortalQuestion,
    PortalSave,
    PortalSection,
    PortalView,
    PreviewScoreRequest,
    PreviewScoreResult,
    PublishRequest,
    QuestionnaireCreate,
    QuestionnaireRead,
    QuestionnaireSummary,
    QuestionnaireUpdate,
    RaiseIssueRequest,
    RcsaRunRequest,
    ReturnRequest,
    SendRequest,
    StructureProblems,
    SubmitAnswers,
    VersionRow,
)
from app.schemas.common import Page
from app.services import audit, vendor_tiering
from app.services import questionnaire_library as library
from app.services import questionnaire_logic as ql
from app.services import questionnaire_portal as portal
from app.services import questionnaire_versions as versions
from app.services import questionnaire_workflow as wf
from app.services.rate_limit import too_many_requests

router = APIRouter(tags=["assessments"])
_READ = Depends(require("assessment:read"))
_WRITE = Depends(require("assessment:write"))


def _http(exc: Exception) -> HTTPException:
    """A service refusal as an HTTP error; listed problems ride in the detail."""
    code = getattr(exc, "status", 422)
    problems = getattr(exc, "problems", None)
    detail: Any = {"message": str(exc), "problems": problems} if problems else str(exc)
    return HTTPException(status_code=code, detail=detail)


async def _tier_vendor(db, assessment: Assessment, user) -> None:
    """A completed tiering assessment (``purpose = vendor_tiering``) of a vendor writes
    the vendor's inherent tier and proposes its criticality (services/vendor_tiering.py,
    audited). Every question must be answered: a blank would count as the safest answer,
    so the completion is refused (422) rather than under-tiering the vendor."""
    if (
        assessment.vendor_id is None
        or not vendor_tiering.is_tiering_questionnaire(assessment.questionnaire)
        or not vendor_tiering.is_completed(assessment)
    ):
        return
    vendor = await db.scalar(
        select(Vendor).where(Vendor.id == assessment.vendor_id, Vendor.deleted.is_(False))
    )
    if vendor is None:
        return
    try:
        await vendor_tiering.write_back(db, vendor, assessment, user)
    except vendor_tiering.TieringError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


# ============================================================ stubbable loaders ===
async def _file_map(db, answer_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
    """Evidence files per answer (``stored_files`` with entity type ``assessment_answer``)."""
    from app.models.collab import StoredFile

    if not answer_ids:
        return {}
    rows = (await db.scalars(
        select(StoredFile)
        .where(StoredFile.entity_type == "assessment_answer", StoredFile.entity_id.in_(answer_ids))
        .order_by(StoredFile.created_at)
    )).all()
    out: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        out.setdefault(row.entity_id, []).append(row)
    return out


async def _active_links(db, aid: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(AssessmentLink).where(
            AssessmentLink.assessment_id == aid, AssessmentLink.revoked_at.is_(None),
            AssessmentLink.expires_at > datetime.now(timezone.utc),
        )
    ) or 0


async def _review_block(db, assessment: Assessment, user) -> str | None:
    """Segregation of duties for the final review: the sender (else whoever created the
    assessment) may not review it while dual control applies to (assessment, review)."""
    from app.services import dual_control

    if user is None:
        return None
    required, rule = await dual_control.dual_control_required(db, "assessment", "review")
    if not required:
        return None
    maker = assessment.sent_by_id or await dual_control.maker_of(db, "assessment", assessment.id, record=assessment)
    if maker is not None and maker == getattr(user, "id", None):
        return REVIEW_SOD_MESSAGE
    return await dual_control.checker_role_refusal(db, rule, module="assessment", action="review",
                                                   checker_id=getattr(user, "id", None), maker_id=maker)


REVIEW_SOD_MESSAGE = (
    "Segregation of duties: whoever sent this assessment can't also give its final review. "
    "Another reviewer must review it."
)


# ============================================================ questionnaires ===
async def _load_questionnaire(db, qid: uuid.UUID) -> Questionnaire:
    obj = await db.scalar(select(Questionnaire).where(Questionnaire.id == qid))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    return obj


async def _fresh_questionnaire(db, qid: uuid.UUID) -> Questionnaire:
    return await db.scalar(
        select(Questionnaire).where(Questionnaire.id == qid).execution_options(populate_existing=True)
    )


async def _questionnaire_read(db, obj: Questionnaire) -> QuestionnaireRead:
    read = QuestionnaireRead.model_validate(obj)
    read.in_use = (await versions.usage_counts(db, [obj.id])).get(obj.id, 0)
    family = await versions.family_versions(db, obj.family_id or obj.id)
    published = next((v for v in family if v.status == VERSION_PUBLISHED), None)
    draft = next((v for v in family if v.status == VERSION_DRAFT), None)
    read.published_version_id = published.id if published else None
    read.published_version = published.version if published else None
    read.draft_version_id = draft.id if draft else None
    return read


def family_rows(rows: list[Any]) -> list[tuple[Any, Any, Any]]:
    """``(representative, published, draft)`` per family: the draft when one is open,
    else the published version, else the newest. Pure."""
    families: dict[Any, list[Any]] = {}
    for r in rows:
        families.setdefault(r.family_id or r.id, []).append(r)
    out = []
    for members in families.values():
        members.sort(key=lambda v: v.version or 1, reverse=True)
        published = next((v for v in members if v.status == VERSION_PUBLISHED), None)
        draft = next((v for v in members if v.status == VERSION_DRAFT), None)
        out.append((draft or published or members[0], published, draft))
    return out


@router.get("/questionnaires", response_model=Page[QuestionnaireSummary], dependencies=[_READ])
async def list_questionnaires(
    db: DbSession,
    search: str | None = None,
    purpose: str | None = None,
    published_only: bool = Query(False, description="Only questionnaires with a published version, as that version (for pickers)."),
    include_generated: bool = False,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[QuestionnaireSummary]:
    stmt = select(Questionnaire)
    if search:
        stmt = stmt.where(Questionnaire.name.ilike(f"%{search}%"))
    if purpose:
        stmt = stmt.where(Questionnaire.purpose == purpose)
    if not include_generated:
        stmt = stmt.where(Questionnaire.origin != "rcsa_run")
    rows = (await db.scalars(stmt)).all()
    grouped = family_rows(list(rows))
    if published_only:
        grouped = [(p, p, d) for _r, p, d in grouped if p is not None]
    key = {"created_at": lambda t: t[0].created_at, "updated_at": lambda t: t[0].updated_at}.get(
        sort_by or "", lambda t: (t[0].name or "").lower())
    grouped.sort(key=key, reverse=sort_dir == "desc")
    items = []
    for rep, pub, draft in grouped[offset: offset + limit]:
        item = QuestionnaireSummary.model_validate(rep)
        item.published_version_id = pub.id if pub else None
        item.published_version = pub.version if pub else None
        item.draft_version_id = draft.id if draft else None
        items.append(item)
    return Page(items=items, total=len(grouped), limit=limit, offset=offset)


@router.post("/questionnaires", response_model=QuestionnaireRead, status_code=201, dependencies=[_WRITE])
async def create_questionnaire(
    body: QuestionnaireCreate, db: DbSession, user: CurrentUser,
    publish: bool = Query(False, description="Publish version 1 straight away (the structure must be valid)."),
) -> QuestionnaireRead:
    tree = versions.normalise_tree(versions.tree_from_payload(body.sections, body.questions) or [])
    problems = versions.tree_problems(tree)
    if problems:
        raise HTTPException(status_code=422, detail={"message": "The questionnaire has problems.", "problems": problems})
    q = await versions.create_family(
        db, tenant_id=user.tenant_id, name=body.name, description=body.description, purpose=body.purpose,
        bands=[b.model_dump() for b in body.bands], tree=tree, change_note=body.change_note,
    )
    await audit.record(
        db, actor=user, action="create", entity_type="questionnaire", entity_id=q.id,
        summary=f"Created questionnaire '{q.name}' (version 1, draft)",
    )
    fresh = await _fresh_questionnaire(db, q.id)
    if publish:
        try:
            await versions.publish(db, fresh, user, body.change_note)
        except versions.VersionError as exc:
            raise _http(exc) from exc
        await audit.record(db, actor=user, action="publish", entity_type="questionnaire", entity_id=q.id,
                           summary=f"Published '{q.name}' version 1")
        fresh = await _fresh_questionnaire(db, q.id)
    return await _questionnaire_read(db, fresh)


@router.patch(
    "/questionnaires/{qid}", response_model=QuestionnaireRead, dependencies=[_WRITE],
    summary="Save a draft version; `sections` (or legacy `questions`) replaces its whole tree",
)
async def update_questionnaire(
    qid: uuid.UUID, body: QuestionnaireUpdate, db: DbSession, user: CurrentUser
) -> QuestionnaireRead:
    obj = await _load_questionnaire(db, qid)
    if not obj.is_editable:
        raise HTTPException(status_code=409, detail=(
            f"Version {obj.version} of '{obj.name}' is {obj.status} and can't be changed. "
            "Create a new version to edit it."))
    data = body.model_dump(exclude_unset=True)
    for field in ("name", "description", "purpose", "change_note"):
        if data.get(field) is not None:
            setattr(obj, field, data[field])
    if body.bands is not None:
        obj.bands = [b.model_dump() for b in body.bands]
    tree = versions.tree_from_payload(body.sections, body.questions)
    if tree is not None:
        tree = versions.normalise_tree(tree)
        problems = versions.tree_problems(tree)
        if problems:
            raise HTTPException(status_code=422, detail={"message": "The questionnaire has problems.", "problems": problems})
        try:
            await versions.replace_tree(db, obj, tree)
        except versions.VersionError as exc:
            raise _http(exc) from exc
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="questionnaire", entity_id=obj.id,
        summary=f"Saved draft version {obj.version} of '{obj.name}'",
    )
    return await _questionnaire_read(db, await _fresh_questionnaire(db, obj.id))


@router.get("/questionnaires/{qid}", response_model=QuestionnaireRead, dependencies=[_READ])
async def get_questionnaire(qid: uuid.UUID, db: DbSession) -> QuestionnaireRead:
    return await _questionnaire_read(db, await _load_questionnaire(db, qid))


@router.get("/questionnaires/{qid}/versions", response_model=list[VersionRow], dependencies=[_READ])
async def questionnaire_versions(qid: uuid.UUID, db: DbSession) -> list[VersionRow]:
    obj = await _load_questionnaire(db, qid)
    rows = await versions.family_versions(db, obj.family_id or obj.id)
    usage = await versions.usage_counts(db, [r.id for r in rows])
    out = []
    for r in rows:
        row = VersionRow.model_validate(r)
        row.in_use = usage.get(r.id, 0)
        out.append(row)
    return out


@router.post("/questionnaires/{qid}/validate", response_model=StructureProblems, dependencies=[_READ])
async def validate_questionnaire(qid: uuid.UUID, db: DbSession) -> StructureProblems:
    obj = await _load_questionnaire(db, qid)
    return StructureProblems(problems=versions.publish_problems(obj, ql.spec_from_version(obj)))


@router.post("/questionnaires/{qid}/publish", response_model=QuestionnaireRead, dependencies=[_WRITE])
async def publish_questionnaire(qid: uuid.UUID, body: PublishRequest, db: DbSession, user: CurrentUser) -> QuestionnaireRead:
    obj = await _load_questionnaire(db, qid)
    try:
        await versions.publish(db, obj, user, body.change_note)
    except versions.VersionError as exc:
        raise _http(exc) from exc
    await audit.record(
        db, actor=user, action="publish", entity_type="questionnaire", entity_id=obj.id,
        summary=f"Published '{obj.name}' version {obj.version}" + (f": {body.change_note}" if body.change_note else ""),
    )
    return await _questionnaire_read(db, await _fresh_questionnaire(db, obj.id))


@router.post("/questionnaires/{qid}/new-version", response_model=QuestionnaireRead, dependencies=[_WRITE],
             summary="Open the next draft version (or return the draft already open)")
async def new_questionnaire_version(qid: uuid.UUID, db: DbSession, user: CurrentUser) -> QuestionnaireRead:
    obj = await _load_questionnaire(db, qid)
    draft, created = await versions.new_version(db, obj, user)
    if created:
        await audit.record(
            db, actor=user, action="create", entity_type="questionnaire", entity_id=draft.id,
            summary=f"Opened draft version {draft.version} of '{draft.name}' from version {obj.version}",
        )
    return await _questionnaire_read(db, await _fresh_questionnaire(db, draft.id))


@router.post("/questionnaires/{qid}/preview-score", response_model=PreviewScoreResult, dependencies=[_READ])
async def preview_score(qid: uuid.UUID, body: PreviewScoreRequest, db: DbSession) -> PreviewScoreResult:
    obj = await _load_questionnaire(db, qid)
    return preview(obj, body.answers)


def preview(version: Any, answers: dict[str, dict[str, Any]]) -> PreviewScoreResult:
    spec = ql.spec_from_version(version)
    values = {
        k: ql.AnswerValue(
            option_values=tuple(str(x) for x in (v.get("option_values") or [])),
            number=v.get("number"), text=v.get("text") or "", date=v.get("date"),
            na=bool(v.get("na")), files=int(v.get("files") or 0),
        )
        for k, v in answers.items()
    }
    vis = ql.visibility(spec, values)
    result = ql.score(spec, values)
    band = ql.band_for(version.bands, result.pct)
    return PreviewScoreResult(
        visible_sections=sorted(vis.sections), visible_questions=sorted(vis.questions),
        earned=result.earned, maximum=result.maximum, pct=result.pct,
        band=str(band.get("label")) if band else "", rating=band.get("rating") if band else None,
        missing_mandatory=list(result.missing_mandatory),
        risk_flags=[f.__dict__ for f in ql.risk_flags(spec, values)],
    )


@router.delete("/questionnaires/{qid}", status_code=204, dependencies=[_WRITE])
async def delete_questionnaire(qid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_questionnaire(db, qid)
    # The assessments.questionnaire_id FK is RESTRICT: refuse up front rather than fail at commit.
    in_use = await db.scalar(
        select(func.count()).select_from(Assessment).where(Assessment.questionnaire_id == qid)
    )
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version {obj.version} is used by {in_use} assessment(s); it can't be deleted.",
        )
    if obj.status == VERSION_PUBLISHED:
        # Deleting the current published version brings back the newest superseded one.
        family = await versions.family_versions(db, obj.family_id or obj.id)
        previous = next((v for v in family if v.id != obj.id and v.status == VERSION_SUPERSEDED), None)
        if previous is not None:
            previous.status = VERSION_PUBLISHED
    await audit.record(
        db, actor=user, action="delete", entity_type="questionnaire", entity_id=obj.id,
        summary=f"Deleted version {obj.version} ({obj.status}) of '{obj.name}'",
    )
    await db.delete(obj)


# ================================================================== library ===
@router.get("/questionnaire-library", response_model=list[LibraryTemplate], dependencies=[_READ])
async def list_library(db: DbSession) -> list[LibraryTemplate]:
    installed = (await db.execute(select(Questionnaire.library_key, Questionnaire.library_version)
                                  .where(Questionnaire.library_key != ""))).all()
    have: dict[str, set[int]] = {}
    for key, version in installed:
        if version is not None:
            have.setdefault(key, set()).add(version)
    return [LibraryTemplate(**library.summary(t), installed_versions=sorted(have.get(t["key"], set())))
            for t in library.TEMPLATES]


@router.get("/questionnaire-library/{key}", dependencies=[_READ])
async def get_library_template(key: str) -> dict:
    template = library.get(key)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/questionnaire-library/{key}/install", response_model=QuestionnaireRead, status_code=201, dependencies=[_WRITE])
async def install_library_template(key: str, body: LibraryInstall, db: DbSession, user: CurrentUser) -> QuestionnaireRead:
    template = library.get(key)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    q = await versions.install_template(db, tenant_id=user.tenant_id, template=template, name=body.name)
    await audit.record(
        db, actor=user, action="create", entity_type="questionnaire", entity_id=q.id,
        summary=f"Installed '{q.name}' from the template library (template version {template['version']}) as a draft",
    )
    return await _questionnaire_read(db, await _fresh_questionnaire(db, q.id))


# =============================================================== assessments ===
async def _load(db, aid: uuid.UUID) -> Assessment:
    obj = await db.scalar(select(Assessment).where(Assessment.id == aid))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return obj


async def _fresh(db, aid: uuid.UUID) -> Assessment:
    return await db.scalar(
        select(Assessment).where(Assessment.id == aid).execution_options(populate_existing=True)
    )


async def _read(db, obj: Assessment, user=None) -> AssessmentRead:
    files = await _file_map(db, [a.id for a in obj.answers])
    obj._file_counts = {k: len(v) for k, v in files.items()}
    read = AssessmentRead.model_validate(obj)
    for answer in read.answers:
        answer.files = [FileRef.model_validate(f) for f in files.get(answer.id, [])]
    read.active_links = await _active_links(db, obj.id)
    if getattr(obj.status, "value", obj.status) in _EDITABLE_IN_APP:
        reopened = _reopened(obj)
        read.reopened_question_ids = sorted(reopened) if reopened is not None else None
    if getattr(obj.status, "value", obj.status) == VendorAssessmentStatus.submitted.value:
        read.review_blocked_reason = await _review_block(db, obj, user)
    return read


_ASSESSMENT_SORTABLE = {
    "title": Assessment.title,
    "status": Assessment.status,
    "due_date": Assessment.due_date,
    "created_at": Assessment.created_at,
}


@router.get("/assessments", response_model=Page[AssessmentSummary], dependencies=[_READ])
async def list_assessments(
    db: DbSession,
    search: str | None = None,
    status_filter: Annotated[VendorAssessmentStatus | None, Query(alias="status")] = None,
    purpose: str | None = None,
    vendor_id: uuid.UUID | None = None,
    overdue: bool = False,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AssessmentSummary]:
    from app.core.listing import ListParams, apply_sort

    stmt = select(Assessment)
    if search:
        stmt = stmt.where(Assessment.title.ilike(f"%{search}%"))
    if status_filter is not None:
        stmt = stmt.where(Assessment.status == status_filter)
    if vendor_id is not None:
        stmt = stmt.where(Assessment.vendor_id == vendor_id)
    if purpose:
        stmt = stmt.where(Assessment.questionnaire_id.in_(select(Questionnaire.id).where(Questionnaire.purpose == purpose)))
    if overdue:
        stmt = stmt.where(Assessment.due_date < date.today(), Assessment.status.in_(
            [VendorAssessmentStatus.draft, VendorAssessmentStatus.sent, VendorAssessmentStatus.in_progress]))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ASSESSMENT_SORTABLE, default=Assessment.created_at)
    else:
        stmt = stmt.order_by(Assessment.created_at.desc())
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[AssessmentSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


async def _published_for(db, questionnaire_id: uuid.UUID) -> Questionnaire:
    q = await _load_questionnaire(db, questionnaire_id)
    if q.status == VERSION_PUBLISHED:
        return q
    published = await versions.published_version(db, q.family_id or q.id)
    if published is None:
        raise HTTPException(status_code=422, detail=(
            f"'{q.name}' has no published version yet. Publish it before starting an assessment."))
    return published


async def _check_vendor(db, vendor_id: uuid.UUID) -> Vendor:
    v = await db.scalar(select(Vendor).where(Vendor.id == vendor_id, Vendor.deleted.is_(False)))
    if v is None:
        raise HTTPException(status_code=400, detail=f"Unknown or archived vendor id: {vendor_id}")
    return v


@router.post("/assessments", response_model=AssessmentRead, status_code=201, dependencies=[_WRITE])
async def create_assessment(body: AssessmentCreate, db: DbSession, user: CurrentUser) -> AssessmentRead:
    version = await _published_for(db, body.questionnaire_id)
    vendor = await _check_vendor(db, body.vendor_id) if body.vendor_id is not None else None
    if body.rcsa_assessment_id is not None:
        from app.models.operational_risk import RcsaAssessment

        if await db.scalar(select(RcsaAssessment.id).where(RcsaAssessment.id == body.rcsa_assessment_id,
                                                           RcsaAssessment.deleted.is_(False))) is None:
            raise HTTPException(status_code=400, detail="Unknown or archived RCSA.")
    obj = Assessment(
        tenant_id=user.tenant_id,
        title=body.title,
        vendor_id=body.vendor_id,
        questionnaire_id=version.id,
        due_date=body.due_date,
        review_notes=body.review_notes,
        access_hash="",
        status=VendorAssessmentStatus.draft,
        contact_name=body.contact_name or (getattr(vendor, "contact_name", "") or ""),
        contact_email=body.contact_email or (getattr(vendor, "contact_email", "") or ""),
        reviewer_id=body.reviewer_id,
        recurrence_months=body.recurrence_months,
        rcsa_assessment_id=body.rcsa_assessment_id,
    )
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="assessment", entity_id=obj.id,
        summary=f"Created assessment '{obj.title}' ({version.name} v{version.version})",
    )
    return await _read(db, await _fresh(db, obj.id), user)


@router.get("/assessments/{aid}", response_model=AssessmentRead, dependencies=[_READ])
async def get_assessment(aid: uuid.UUID, db: DbSession, user: CurrentUser) -> AssessmentRead:
    return await _read(db, await _load(db, aid), user)


@router.patch(
    "/assessments/{aid}", response_model=AssessmentRead, dependencies=[_WRITE],
    summary="Update the assessment header (title, vendor, contact, reviewer, due date, recurrence, notes)",
)
async def update_assessment(aid: uuid.UUID, body: AssessmentUpdate, db: DbSession, user: CurrentUser) -> AssessmentRead:
    obj = await _load(db, aid)
    data = body.model_dump(exclude_unset=True)
    new_status = data.get("status")
    if new_status is not None and getattr(new_status, "value", new_status) != getattr(obj.status, "value", obj.status):
        if new_status in (VendorAssessmentStatus.submitted, VendorAssessmentStatus.reviewed):
            raise HTTPException(status_code=422, detail=(
                "Use Submit and Review to complete an assessment: they check required answers, "
                "score it and apply segregation of duties."))
    if data.get("questionnaire_id") is not None and data["questionnaire_id"] != obj.questionnaire_id:
        if obj.answers:
            raise HTTPException(status_code=409, detail="Answers have been given against this questionnaire; start a new assessment instead.")
        data["questionnaire_id"] = (await _published_for(db, data["questionnaire_id"])).id
    if data.get("vendor_id") is not None:
        await _check_vendor(db, data["vendor_id"])
    was_completed = vendor_tiering.is_completed(obj)
    old_vendor = obj.vendor_id
    for field, value in data.items():
        setattr(obj, field, value)
    await db.flush()
    await audit.record(
        db, actor=user, action="update", entity_type="assessment", entity_id=obj.id,
        summary=f"Updated assessment '{obj.title}'",
    )
    fresh = await _fresh(db, aid)
    # Re-pointing a completed tiering assessment at another vendor tiers that vendor.
    if not was_completed or fresh.vendor_id != old_vendor:
        await _tier_vendor(db, fresh, user)
    return await _read(db, fresh, user)


async def _submit(db, assessment: Assessment, actor, *, submitted_by: str) -> Assessment:
    """Shared by the app and the portal: required answers, score + band, flagged findings,
    tiering, audit and a notification to the sender and reviewer."""
    unchanged = wf.returned_refusal(assessment)
    if unchanged is not None:
        raise _http(unchanged)
    files = await _file_map(db, [a.id for a in assessment.answers])
    counts = {k: len(v) for k, v in files.items()}
    spec, values, result = wf.evaluate(assessment, counts)
    refusal = wf.submit_refusal(result, spec)
    if refusal is not None:
        raise _http(refusal)
    assessment.status = VendorAssessmentStatus.submitted
    assessment.submitted_at = date.today()
    assessment.submitted_by = submitted_by[:255]
    wf.snapshot(assessment, result)
    created, closed = wf.sync_flag_findings(assessment, spec, values, tenant_id=assessment.tenant_id)
    for f in created:
        db.add(f)
    await db.flush()
    fresh = await _fresh(db, assessment.id)
    await _tier_vendor(db, fresh, actor)
    await audit.record(
        db, actor=actor, action="submit", entity_type="assessment", entity_id=fresh.id,
        summary=(f"Submitted '{fresh.title}': {result.pct if result.pct is not None else '–'}%"
                 f"{' (' + fresh.result_band + ')' if fresh.result_band else ''}; "
                 f"{len(created)} finding{'s' if len(created) != 1 else ''} raised from flagged answers"
                 + (f", {closed} closed" if closed else "")),
        changes={"score_pct": result.pct, "band": fresh.result_band, "findings_raised": len(created)},
    )
    for uid in {fresh.sent_by_id, fresh.reviewer_id} - {None, getattr(actor, "id", None)}:
        from app.models.enums import NotificationCategory

        db.add(wf.event_notification(
            fresh.tenant_id, fresh, user_id=uid, key=f"assessment-submitted:{fresh.id}:{uid}:{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
            title=f"Assessment submitted: {fresh.title}",
            body=f"'{fresh.title}' was submitted by {submitted_by}. Review each answer, then give the final review.",
            category=NotificationCategory.info,
        ))
    return fresh


_EDITABLE_IN_APP = ("draft", "sent", "in_progress")


@router.post(
    "/assessments/{aid}/answers", response_model=AssessmentRead, dependencies=[_WRITE],
    summary="Save answers in the app (typed values, N/A, comments); optionally submit",
)
async def submit_answers(aid: uuid.UUID, body: SubmitAnswers, db: DbSession, user: CurrentUser) -> AssessmentRead:
    assessment = await _load(db, aid)
    state = getattr(assessment.status, "value", assessment.status)
    if state not in _EDITABLE_IN_APP:
        raise HTTPException(status_code=409, detail=(
            f"The assessment is {state.replace('_', ' ')}; answers can't change now. "
            "Return answers to the respondent to reopen them."))
    try:
        new_rows, _changed = wf.upsert_answers(
            assessment, body.answers, tenant_id=user.tenant_id, answered_by=user.email,
            only_questions=_reopened(assessment),
        )
    except wf.WorkflowError as exc:
        raise _http(exc) from exc
    for row in new_rows:
        db.add(row)
    if state in ("draft", "sent"):
        assessment.status = VendorAssessmentStatus.in_progress
    await db.flush()
    fresh = await _fresh(db, aid)
    if body.submit:
        fresh = await _submit(db, fresh, user, submitted_by=user.email)
    return await _read(db, fresh, user)


@router.post("/assessments/{aid}/submit", response_model=AssessmentRead, dependencies=[_WRITE])
async def submit_assessment(aid: uuid.UUID, db: DbSession, user: CurrentUser) -> AssessmentRead:
    assessment = await _load(db, aid)
    if getattr(assessment.status, "value", assessment.status) not in _EDITABLE_IN_APP:
        raise HTTPException(status_code=409, detail="Only an assessment that is still being answered can be submitted.")
    return await _read(db, await _submit(db, assessment, user, submitted_by=user.email), user)


# ---------------------------------------------------------------- send + links
def _link_read(link: AssessmentLink) -> LinkRead:
    read = LinkRead.model_validate(link)
    read.state = portal.link_state(link, datetime.now(timezone.utc))
    return read


async def _organisation(db, tenant_id: uuid.UUID) -> str:
    from app.models.tenant import Tenant

    tenant = await db.get(Tenant, tenant_id)
    return getattr(tenant, "name", "") or "Your bank"


async def _issue(db, assessment: Assessment, user, body: LinkCreate, *, reason: str) -> tuple[AssessmentLink, str, bool]:
    name = body.contact_name or assessment.contact_name
    email_addr = body.contact_email or assessment.contact_email
    if not email_addr:
        raise HTTPException(status_code=422, detail="contact_email: give the respondent's e-mail address.")
    link, token = portal.issue_link(
        tenant_id=assessment.tenant_id, assessment_id=assessment.id, contact_name=name, contact_email=email_addr,
        expires_in_days=body.expires_in_days, reason=reason, created_by_id=user.id,
    )
    db.add(link)
    await db.flush()
    emailed = False
    if body.send_email:
        emailed = await wf.email_link("invite", organisation=await _organisation(db, assessment.tenant_id),
                                      assessment=assessment, link=link, token=token, message=body.message)
    return link, token, emailed


@router.post("/assessments/{aid}/send", response_model=LinkIssued, dependencies=[_WRITE],
             summary="Send the assessment: a respondent link for the contact, e-mailed when mail is set up")
async def send_assessment(aid: uuid.UUID, body: SendRequest, db: DbSession, user: CurrentUser) -> LinkIssued:
    assessment = await _load(db, aid)
    state = getattr(assessment.status, "value", assessment.status)
    if state not in ("draft", "sent", "in_progress"):
        raise HTTPException(status_code=409, detail=f"The assessment is {state}; it can't be sent.")
    if body.contact_email:
        assessment.contact_email = body.contact_email
    if body.contact_name:
        assessment.contact_name = body.contact_name
    link, token, emailed = await _issue(db, assessment, user, body, reason="initial")
    if state == "draft":
        assessment.status = VendorAssessmentStatus.sent
    assessment.sent_at = datetime.now(timezone.utc)
    assessment.sent_by_id = user.id
    await db.flush()
    await audit.record(
        db, actor=user, action="send", entity_type="assessment", entity_id=assessment.id,
        summary=f"Sent '{assessment.title}' to {link.contact_email}" + ("" if emailed else " (link not e-mailed: copy it from the app)"),
        changes={"link_id": str(link.id), "expires_at": link.expires_at.isoformat(), "emailed": emailed},
    )
    if assessment.reviewer_id and assessment.reviewer_id != user.id:
        from app.models.enums import NotificationCategory

        db.add(wf.event_notification(
            assessment.tenant_id, assessment, user_id=assessment.reviewer_id, key=f"assessment-sent:{assessment.id}",
            title=f"You review: {assessment.title}",
            body=f"'{assessment.title}' was sent to {link.contact_email}. You are its reviewer.",
            category=NotificationCategory.info,
        ))
    fresh = await _fresh(db, aid)
    return LinkIssued(link=_link_read(link), token=token, url=portal.respond_url(token), emailed=emailed,
                      assessment=await _read(db, fresh, user))


@router.get("/assessments/{aid}/links", response_model=list[LinkRead], dependencies=[_READ])
async def list_links(aid: uuid.UUID, db: DbSession) -> list[LinkRead]:
    await _load(db, aid)
    rows = (await db.scalars(select(AssessmentLink).where(AssessmentLink.assessment_id == aid)
                             .order_by(AssessmentLink.created_at.desc()))).all()
    return [_link_read(r) for r in rows]


@router.post("/assessments/{aid}/links", response_model=LinkIssued, status_code=201, dependencies=[_WRITE])
async def create_link(aid: uuid.UUID, body: LinkCreate, db: DbSession, user: CurrentUser) -> LinkIssued:
    assessment = await _load(db, aid)
    if getattr(assessment.status, "value", assessment.status) not in ("sent", "in_progress", "submitted"):
        raise HTTPException(status_code=409, detail="Send the assessment first.")
    link, token, emailed = await _issue(db, assessment, user, body, reason="manual")
    await audit.record(db, actor=user, action="issue_link", entity_type="assessment", entity_id=aid,
                       summary=f"New respondent link for {link.contact_email} on '{assessment.title}'",
                       changes={"link_id": str(link.id), "emailed": emailed})
    return LinkIssued(link=_link_read(link), token=token, url=portal.respond_url(token), emailed=emailed)


async def _load_link(db, aid: uuid.UUID, lid: uuid.UUID) -> AssessmentLink:
    link = await db.scalar(select(AssessmentLink).where(AssessmentLink.id == lid, AssessmentLink.assessment_id == aid))
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return link


@router.post("/assessments/{aid}/links/{lid}/revoke", response_model=LinkRead, dependencies=[_WRITE])
async def revoke_link(aid: uuid.UUID, lid: uuid.UUID, db: DbSession, user: CurrentUser) -> LinkRead:
    link = await _load_link(db, aid, lid)
    if link.revoked_at is None:
        link.revoked_at = datetime.now(timezone.utc)
        link.revoked_by_id = user.id
        await db.flush()
        await audit.record(db, actor=user, action="revoke_link", entity_type="assessment", entity_id=aid,
                           summary=f"Revoked the respondent link for {link.contact_email}",
                           changes={"link_id": str(link.id)})
    return _link_read(link)


@router.post("/assessments/{aid}/links/{lid}/resend", response_model=LinkIssued, dependencies=[_WRITE],
             summary="Revoke a link and issue a new one to the same contact")
async def resend_link(aid: uuid.UUID, lid: uuid.UUID, body: LinkCreate, db: DbSession, user: CurrentUser) -> LinkIssued:
    assessment = await _load(db, aid)
    old = await _load_link(db, aid, lid)
    if old.revoked_at is None:
        old.revoked_at = datetime.now(timezone.utc)
        old.revoked_by_id = user.id
    body = LinkCreate(contact_name=body.contact_name or old.contact_name, contact_email=body.contact_email or old.contact_email,
                      expires_in_days=body.expires_in_days, send_email=body.send_email, message=body.message)
    link, token, emailed = await _issue(db, assessment, user, body, reason="resend")
    await audit.record(db, actor=user, action="issue_link", entity_type="assessment", entity_id=aid,
                       summary=f"Resent the respondent link to {link.contact_email} (previous link revoked)",
                       changes={"link_id": str(link.id), "revoked_link_id": str(old.id), "emailed": emailed})
    return LinkIssued(link=_link_read(link), token=token, url=portal.respond_url(token), emailed=emailed)


@router.get("/assessments/{aid}/access-log", response_model=list[AccessLogRead], dependencies=[_READ])
async def access_log(aid: uuid.UUID, db: DbSession, limit: Annotated[int, Query(ge=1, le=500)] = 200) -> list[AccessLogRead]:
    await _load(db, aid)
    rows = (await db.scalars(select(AssessmentAccessLog).where(AssessmentAccessLog.assessment_id == aid)
                             .order_by(AssessmentAccessLog.created_at.desc()).limit(limit))).all()
    return [AccessLogRead.model_validate(r) for r in rows]


# -------------------------------------------------------------------- review
@router.post("/assessments/{aid}/answers/{answer_id}/review", response_model=AssessmentRead, dependencies=[_WRITE],
             summary="Accept an answer, or return it to the respondent with a comment")
async def review_answer(aid: uuid.UUID, answer_id: uuid.UUID, body: AnswerReview, db: DbSession, user: CurrentUser) -> AssessmentRead:
    assessment = await _load(db, aid)
    if getattr(assessment.status, "value", assessment.status) != VendorAssessmentStatus.submitted.value:
        raise HTTPException(status_code=409, detail="Answers are reviewed once the assessment is submitted.")
    answer = next((a for a in assessment.answers if a.id == answer_id), None)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    try:
        wf.review_answer(answer, body.decision, body.comment, user.id)
    except wf.WorkflowError as exc:
        raise _http(exc) from exc
    await db.flush()
    await audit.record(db, actor=user, action="review_answer", entity_type="assessment", entity_id=aid,
                       summary=f"{'Accepted' if body.decision == 'accept' else 'Returned'} an answer on '{assessment.title}'"
                               + (f": {body.comment}" if body.comment else ""),
                       changes={"answer_id": str(answer.id), "decision": body.decision})
    return await _read(db, await _fresh(db, aid), user)


@router.post("/assessments/{aid}/return", response_model=AssessmentRead, dependencies=[_WRITE],
             summary="Send the returned answers back to the respondent")
async def return_assessment(aid: uuid.UUID, body: ReturnRequest, db: DbSession, user: CurrentUser) -> AssessmentRead:
    assessment = await _load(db, aid)
    if getattr(assessment.status, "value", assessment.status) != VendorAssessmentStatus.submitted.value:
        raise HTTPException(status_code=409, detail="Only a submitted assessment can be returned.")
    returned = assessment.returned_count
    if not returned:
        raise HTTPException(status_code=422, detail="Return at least one answer (with a comment) first.")
    assessment.status = VendorAssessmentStatus.in_progress
    await db.flush()
    emailed = False
    if assessment.contact_email:
        link, token = portal.issue_link(
            tenant_id=assessment.tenant_id, assessment_id=aid, contact_name=assessment.contact_name,
            contact_email=assessment.contact_email, reason="resend", created_by_id=user.id,
        )
        db.add(link)
        await db.flush()
        emailed = await wf.email_link("returned", organisation=await _organisation(db, assessment.tenant_id),
                                      assessment=assessment, link=link, token=token, message=body.message, returned=returned)
    await audit.record(db, actor=user, action="return", entity_type="assessment", entity_id=aid,
                       summary=f"Returned {returned} answer{'s' if returned != 1 else ''} on '{assessment.title}' to the respondent"
                               + ("" if emailed else " (not e-mailed)"),
                       changes={"returned": returned, "emailed": emailed})
    return await _read(db, await _fresh(db, aid), user)


@router.post("/assessments/{aid}/review", response_model=AssessmentRead, dependencies=[_WRITE],
             summary="Final review (maker-checker): score, band and the records the results drive")
async def review_assessment(aid: uuid.UUID, body: AssessmentReviewRequest, db: DbSession, user: CurrentUser) -> AssessmentRead:
    assessment = await _load(db, aid)
    refusal = wf.review_refusal(assessment)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    blocked = await _review_block(db, assessment, user)
    if blocked:
        raise HTTPException(status_code=403, detail=blocked)
    now = datetime.now(timezone.utc)
    for a in assessment.answers:
        if a.review_state == REVIEW_PENDING:
            a.review_state, a.reviewed_by_id, a.reviewed_at = REVIEW_ACCEPTED, user.id, now
    files = await _file_map(db, [a.id for a in assessment.answers])
    _spec, _values, result = wf.evaluate(assessment, {k: len(v) for k, v in files.items()})
    wf.snapshot(assessment, result)
    assessment.status = VendorAssessmentStatus.reviewed
    assessment.reviewed_at = now
    assessment.reviewed_by_id = user.id
    if body.notes:
        assessment.review_notes = body.notes
    if assessment.recurrence_months:
        assessment.next_issue_on = wf.next_due(date.today(), assessment.recurrence_months)
    await db.flush()
    await audit.record(
        db, actor=user, action="review", entity_type="assessment", entity_id=aid,
        summary=f"Reviewed '{assessment.title}': {result.pct if result.pct is not None else '–'}%"
                + (f" ({assessment.result_band})" if assessment.result_band else ""),
        changes={"score_pct": result.pct, "band": assessment.result_band, "rating": assessment.result_rating},
    )
    fresh = await _fresh(db, aid)
    await _apply_results(db, fresh, user)
    return await _read(db, await _fresh(db, aid), user)


async def _apply_results(db, assessment: Assessment, user) -> None:
    purpose = assessment.purpose
    if purpose == vendor_tiering.TIERING_PURPOSE:
        await _tier_vendor(db, assessment, user)
    elif purpose == "vendor_due_diligence" and assessment.vendor_id is not None:
        vendor = await db.scalar(select(Vendor).where(Vendor.id == assessment.vendor_id, Vendor.deleted.is_(False)))
        if vendor is not None:
            await wf.apply_due_diligence(db, vendor, assessment, user)
    elif purpose == "rcsa_control_self_assessment":
        await wf.apply_rcsa(db, assessment, user)


# ------------------------------------------------------------------ findings
@router.post("/assessments/{aid}/findings", response_model=AssessmentRead, status_code=201, dependencies=[_WRITE])
async def add_finding(aid: uuid.UUID, body: FindingCreate, db: DbSession, user: CurrentUser) -> AssessmentRead:
    await _load(db, aid)
    db.add(AssessmentFinding(tenant_id=user.tenant_id, assessment_id=aid, **body.model_dump()))
    await db.flush()
    return await _read(db, await _fresh(db, aid), user)


async def _load_finding(db, aid: uuid.UUID, fid: uuid.UUID) -> AssessmentFinding:
    finding = await db.scalar(
        select(AssessmentFinding).where(AssessmentFinding.id == fid, AssessmentFinding.assessment_id == aid)
    )
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return finding


@router.patch("/assessments/{aid}/findings/{fid}", response_model=AssessmentRead, dependencies=[_WRITE],
              summary="Edit a finding (title, description, severity, status, deadline)")
async def update_finding(aid: uuid.UUID, fid: uuid.UUID, body: FindingUpdate, db: DbSession, user: CurrentUser) -> AssessmentRead:
    finding = await _load_finding(db, aid, fid)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(finding, field, value)
    await db.flush()
    return await _read(db, await _fresh(db, aid), user)


@router.post("/assessments/{aid}/findings/{fid}/close", response_model=AssessmentRead, dependencies=[_WRITE])
async def close_finding(aid: uuid.UUID, fid: uuid.UUID, db: DbSession, user: CurrentUser) -> AssessmentRead:
    finding = await _load_finding(db, aid, fid)
    finding.status = FindingStatus.closed
    await db.flush()
    return await _read(db, await _fresh(db, aid), user)


@router.post("/assessments/{aid}/findings/{fid}/issue", response_model=AssessmentRead, dependencies=[_WRITE],
             summary="Raise a finding to an Issue (source: assessment; linked to the vendor)")
async def raise_finding_issue(aid: uuid.UUID, fid: uuid.UUID, body: RaiseIssueRequest, db: DbSession, user: CurrentUser) -> AssessmentRead:
    from app.api.v1 import issues as issues_api
    from app.models.issue import IssueSource
    from app.schemas.issue import IssueCreate

    if "issue:write" not in (getattr(user, "permission_codes", None) or []):
        raise HTTPException(status_code=403, detail="Raising an issue needs permission to create issues (issue:write).")
    assessment = await _load(db, aid)
    finding = await _load_finding(db, aid, fid)
    if finding.issue_id is not None and finding.issue_ref is not None:
        raise HTTPException(status_code=409, detail=f"Already raised as {finding.issue_ref['reference']}.")
    description = finding.description or ""
    context = f"From assessment '{assessment.title}'" + (f" of {assessment.vendor.name}" if assessment.vendor else "") + "."
    issue = await issues_api.create_issue(
        body=IssueCreate(
            title=body.title or finding.title, description=body.description or f"{description}\n\n{context}".strip(),
            source_type=IssueSource.assessment, source_reference=f"{assessment.title}: {finding.title}"[:255],
            source_id=assessment.id, severity=body.severity or finding.severity, owner_id=body.owner_id,
            due_date=body.due_date or finding.deadline,
            vendor_ids=[assessment.vendor_id] if assessment.vendor_id else [],
        ),
        db=db, user=user,
    )
    finding.issue_id = issue.id
    await db.flush()
    await audit.record(db, actor=user, action="raise_issue", entity_type="assessment", entity_id=aid,
                       summary=f"Raised finding '{finding.title}' as {issue.reference}",
                       changes={"finding_id": str(finding.id), "issue_id": str(issue.id)})
    return await _read(db, await _fresh(db, aid), user)


@router.post("/assessments/{aid}/questions/{question_id}/files", response_model=AssessmentRead, status_code=201,
             dependencies=[_WRITE], summary="Attach evidence to an answer in the app")
async def upload_answer_file(aid: uuid.UUID, question_id: uuid.UUID, db: DbSession, user: CurrentUser,
                             file: UploadFile = File(...)) -> AssessmentRead:
    assessment = await _load(db, aid)
    if getattr(assessment.status, "value", assessment.status) not in _EDITABLE_IN_APP:
        raise HTTPException(status_code=409, detail="Evidence can be added while the assessment is being answered.")
    await _attach(db, assessment, question_id, file, uploaded_by=user.email)
    return await _read(db, await _fresh(db, aid), user)


@router.delete("/assessments/{aid}", status_code=204, dependencies=[_WRITE])
async def delete_assessment(aid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, aid)
    await audit.record(db, actor=user, action="delete", entity_type="assessment", entity_id=aid,
                       summary=f"Deleted assessment '{obj.title}'")
    await db.delete(obj)


# ====================================================================== RCSA ===
@router.post("/rcsa/{rid}/self-assessment", response_model=AssessmentRead, status_code=201,
             dependencies=[_WRITE, Depends(require("oprisk:read"))],
             summary="Run an RCSA as a control self-assessment questionnaire (one section per line)")
async def run_rcsa_questionnaire(rid: uuid.UUID, body: RcsaRunRequest, db: DbSession, user: CurrentUser) -> AssessmentRead:
    from app.models.operational_risk import RcsaAssessment

    rcsa = await db.scalar(select(RcsaAssessment).where(RcsaAssessment.id == rid, RcsaAssessment.deleted.is_(False)))
    if rcsa is None:
        raise HTTPException(status_code=404, detail="RCSA not found")
    if not rcsa.risks:
        raise HTTPException(status_code=422, detail="Add the RCSA's risk and control lines first.")
    blueprint_row = await db.scalar(
        select(Questionnaire).where(Questionnaire.purpose == "rcsa_control_self_assessment",
                                    Questionnaire.status == VERSION_PUBLISHED, Questionnaire.origin != "rcsa_run")
        .order_by(Questionnaire.published_at.desc()).limit(1)
    )
    if blueprint_row is not None:
        blueprint, bands = ql.spec_from_version(blueprint_row), list(blueprint_row.bands or [])
        guidance = {q.key: q.guidance for q in blueprint_row.questions}
        for s in blueprint:
            for q in s["questions"]:
                q["guidance"] = guidance.get(q["key"], "")
        source = f"'{blueprint_row.name}' v{blueprint_row.version}"
    else:
        template = library.get("rcsa-control-self-assessment")
        blueprint, bands, source = template["sections"], template["bands"], "the shipped RCSA template"
    tree = wf.build_rcsa_tree(blueprint, list(rcsa.risks))
    name = f"{rcsa.reference or 'RCSA'} control self-assessment"
    version = await versions.create_family(
        db, tenant_id=user.tenant_id, name=name, description=f"Generated for {rcsa.reference} {rcsa.title} from {source}.",
        purpose="rcsa_control_self_assessment", bands=bands, tree=tree, origin="rcsa_run",
    )
    version = await _fresh_questionnaire(db, version.id)
    try:
        await versions.publish(db, version, user, f"Generated for {rcsa.reference}")
    except versions.VersionError as exc:
        raise _http(exc) from exc
    obj = Assessment(
        tenant_id=user.tenant_id, title=body.title or f"{rcsa.reference} {rcsa.title} — control self-assessment"[:255],
        questionnaire_id=version.id, status=VendorAssessmentStatus.draft, due_date=body.due_date or rcsa.due_date,
        reviewer_id=body.reviewer_id, rcsa_assessment_id=rcsa.id, access_hash="",
    )
    db.add(obj)
    await db.flush()
    await audit.record(db, actor=user, action="create", entity_type="assessment", entity_id=obj.id,
                       summary=f"Started a control self-assessment questionnaire for {rcsa.reference} ({len(rcsa.risks)} lines)")
    return await _read(db, await _fresh(db, obj.id), user)


# ======================================================== respondent portal ===
respond_router = APIRouter(prefix="/respond", tags=["respondent portal"])


def _denied() -> HTTPException:
    return HTTPException(status_code=404, detail=(
        "This link is not valid. It may have expired or been replaced; ask the bank for a new link."))


async def _attach(db, assessment: Assessment, question_id: uuid.UUID, file: UploadFile, *, uploaded_by: str):
    from app.core.config import settings
    from app.models.collab import StoredFile
    from app.services import storage

    question = wf.question_index(assessment.questionnaire).get(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    refusal = portal.upload_refusal(file.filename, file.content_type)
    if refusal:
        raise HTTPException(status_code=415, detail=refusal)
    answer = next((a for a in assessment.answers if a.question_id == question_id), None)
    if answer is None:
        answer = AssessmentAnswer(tenant_id=assessment.tenant_id, assessment_id=assessment.id, question_id=question_id,
                                  answered_by=uploaded_by[:255], answered_at=datetime.now(timezone.utc))
        db.add(answer)
        await db.flush()
    elif answer.review_state in (REVIEW_RETURNED, REVIEW_ACCEPTED):
        # New evidence is a change to the answer: back to the reviewer, stamped so the
        # returned round still counts it as revised.
        answer.review_state = REVIEW_PENDING
        answer.answered_by, answer.answered_at = uploaded_by[:255], datetime.now(timezone.utc)
    existing = (await _file_map(db, [answer.id])).get(answer.id, [])
    if len(existing) >= portal.MAX_FILES_PER_ANSWER:
        raise HTTPException(status_code=422, detail=f"An answer can carry up to {portal.MAX_FILES_PER_ANSWER} files.")
    cap = min(portal.MAX_UPLOAD_MB, settings.max_upload_mb)
    blob = await storage.save_upload(assessment.tenant_id, file)  # streams; refuses above the global cap
    if blob.size_bytes > cap * 1024 * 1024:
        storage.delete_object(blob.storage_key)
        raise HTTPException(status_code=413, detail=f"Files can be up to {cap} MB.")
    sf = StoredFile(
        tenant_id=assessment.tenant_id, entity_type="assessment_answer", entity_id=answer.id, title=blob.filename,
        filename=blob.filename, content_type=blob.content_type, size_bytes=blob.size_bytes, sha256=blob.sha256,
        storage_key=blob.storage_key, uploaded_by_email=uploaded_by[:255],
    )
    db.add(sf)
    await db.flush()
    return sf


class _Opened:
    def __init__(self, db, link, assessment, organisation):
        self.db, self.link, self.assessment, self.organisation = db, link, assessment, organisation


async def _open(db, token: str, request: Request, action: str) -> _Opened:
    """Validate a portal token (rate limit, hash, expiry, revocation), log the access, and
    return the link and assessment. Every refusal that names this organisation is logged."""
    from app.models.tenant import Tenant

    ip = portal.client_address(request)
    decision = await portal.ip_limiter.hit(ip or "unknown")
    if not decision.allowed:
        raise too_many_requests(decision)
    parsed = portal.parse_token(token)
    if parsed is None:
        raise _denied()
    tenant_id, link_id = parsed
    decision = await portal.link_limiter.hit(link_id.hex)
    if not decision.allowed:
        raise too_many_requests(decision)
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or not getattr(tenant, "is_active", True):
        raise _denied()
    link = await db.get(AssessmentLink, link_id)
    if link is None or link.tenant_id != tenant_id or not portal.token_matches(token, link.token_hash):
        db.add(portal.access_log(tenant_id=tenant_id, assessment_id=getattr(link, "assessment_id", None) if link else None,
                                 link_id=None, action="denied", request=request, outcome="denied", detail=f"{action}: wrong token"))
        await db.commit()
        raise _denied()
    now = datetime.now(timezone.utc)
    state = portal.link_state(link, now)
    if state != portal.ACTIVE:
        db.add(portal.access_log(tenant_id=tenant_id, assessment_id=link.assessment_id, link_id=link.id, action="denied",
                                 request=request, outcome="denied", detail=f"{action}: link {state}"))
        await db.commit()
        raise HTTPException(status_code=410, detail=(
            "This link has expired. Ask the bank to send you a new one." if state == portal.EXPIRED
            else "This link has been withdrawn. Ask the bank for a new one."))
    assessment = await db.scalar(select(Assessment).where(Assessment.id == link.assessment_id))
    if assessment is None:
        raise _denied()
    link.last_used_at = now
    link.use_count = (link.use_count or 0) + 1
    db.add(portal.access_log(tenant_id=tenant_id, assessment_id=assessment.id, link_id=link.id, action=action, request=request))
    return _Opened(db, link, assessment, tenant.name)


def _reopened(assessment: Assessment) -> set[uuid.UUID] | None:
    """What the respondent may change in a returned round (``services.questionnaire_workflow``)."""
    return wf.reopened_questions(assessment)


async def _portal_view(db, opened: _Opened) -> PortalView:
    a = opened.assessment
    version = a.questionnaire
    spec = ql.spec_from_version(version)
    guidance = {q.id: q.guidance or "" for q in version.questions}
    files = await _file_map(db, [x.id for x in a.answers])
    state = getattr(a.status, "value", a.status)
    reopened = _reopened(a)
    sections = [
        PortalSection(
            id=s["id"], key=s["key"], title=s["title"], description=s.get("description") or "", conditions=s["conditions"],
            questions=[PortalQuestion(
                id=q["id"], key=q["key"], text=q["text"], guidance=guidance.get(q["id"], ""), type=q["type"],
                mandatory=q["mandatory"], conditions=q["conditions"],
                options=[PortalOption(id=o["id"], value=o["value"], label=o["label"], is_na=o["is_na"]) for o in q["options"]],
            ) for q in s["questions"]],
        )
        for s in spec
    ]
    answers = [
        PortalAnswer(
            question_id=x.question_id,
            option_ids=[x.option_id] if x.option_id else [uuid.UUID(str(i)) for i in (x.option_ids or [])],
            value_text=x.value_text or "", value_number=x.value_number, value_date=x.value_date,
            not_applicable=bool(x.not_applicable), comment=x.comment or "", review_state=x.review_state or "pending",
            review_comment=x.review_comment if x.review_state == REVIEW_RETURNED else "",
            files=[FileRef.model_validate(f) for f in files.get(x.id, [])],
        )
        for x in a.answers
    ]
    editable = state in portal.EDITABLE_STATUSES
    message = ""
    if state == "submitted":
        message = "Thank you. Your answers have been submitted and are being reviewed."
    elif state == "reviewed":
        message = "This questionnaire has been reviewed. No further changes are needed."
    elif state == "draft":
        message = "This questionnaire is not open yet."
    elif reopened:
        message = "The reviewer has returned some answers with comments. Update them and submit again."
    return PortalView(
        organisation=opened.organisation, assessment_title=a.title, vendor_name=a.vendor.name if a.vendor else "",
        questionnaire_name=version.name, questionnaire_version=version.version, contact_name=opened.link.contact_name,
        due_date=a.due_date, status=state, editable=editable, reopened_question_ids=sorted(reopened) if reopened else None,
        submitted_at=a.submitted_at, expires_at=opened.link.expires_at, sections=sections, answers=answers,
        max_upload_mb=portal.MAX_UPLOAD_MB, allowed_file_types=sorted(e.lstrip(".") for e in portal.ALLOWED_EXTENSIONS),
        message=message,
    )


def _require_editable(assessment: Assessment) -> None:
    state = getattr(assessment.status, "value", assessment.status)
    if state not in portal.EDITABLE_STATUSES:
        raise HTTPException(status_code=409, detail=(
            "This questionnaire has been submitted and can't be changed." if state in ("submitted", "reviewed")
            else "This questionnaire is not open for answers."))


async def _portal_session(token: str):
    from app.core.database import tenant_session

    parsed = portal.parse_token(token)
    if parsed is None:
        raise _denied()
    return tenant_session(parsed[0])


@respond_router.get("/{token}", response_model=PortalView, summary="Open a questionnaire from a respondent link (no sign-in)")
async def portal_view(token: str, request: Request) -> PortalView:
    async with await _portal_session(token) as db:
        opened = await _open(db, token, request, "view")
        return await _portal_view(db, opened)


@respond_router.put("/{token}/answers", response_model=PortalView, summary="Save answers as a draft")
async def portal_save(token: str, body: PortalSave, request: Request) -> PortalView:
    async with await _portal_session(token) as db:
        opened = await _open(db, token, request, "save")
        a = opened.assessment
        _require_editable(a)
        actor = portal.portal_actor(a.tenant_id, opened.link)
        try:
            new_rows, changed = wf.upsert_answers(a, body.answers, tenant_id=a.tenant_id, answered_by=actor.email,
                                                   only_questions=_reopened(a))
        except wf.WorkflowError as exc:
            raise _http(exc) from exc
        for row in new_rows:
            db.add(row)
        if getattr(a.status, "value", a.status) == "sent":
            a.status = VendorAssessmentStatus.in_progress
        await db.flush()
        if changed:
            await audit.record(db, actor=actor, action="respond_save", entity_type="assessment", entity_id=a.id,
                               summary=f"Saved {changed} answer{'s' if changed != 1 else ''} on '{a.title}' through the respondent link",
                               changes={"link_id": str(opened.link.id), "ip": portal.client_address(request)})
        opened.assessment = await _fresh(db, a.id)
        return await _portal_view(db, opened)


@respond_router.post("/{token}/questions/{question_id}/files", response_model=PortalView, status_code=201,
                     summary="Upload evidence for an answer")
async def portal_upload(token: str, question_id: uuid.UUID, request: Request, file: UploadFile = File(...)) -> PortalView:
    async with await _portal_session(token) as db:
        opened = await _open(db, token, request, "upload")
        a = opened.assessment
        _require_editable(a)
        reopened = _reopened(a)
        if reopened is not None and question_id not in reopened:
            raise HTTPException(status_code=409, detail=wf.REOPENED_ONLY)
        actor = portal.portal_actor(a.tenant_id, opened.link)
        sf = await _attach(db, a, question_id, file, uploaded_by=actor.email)
        if getattr(a.status, "value", a.status) == "sent":
            a.status = VendorAssessmentStatus.in_progress
        await audit.record(db, actor=actor, action="respond_upload", entity_type="assessment", entity_id=a.id,
                           summary=f"Uploaded {sf.filename} ({sf.size_bytes} bytes) on '{a.title}' through the respondent link",
                           changes={"file_id": str(sf.id), "sha256": sf.sha256, "link_id": str(opened.link.id)})
        opened.assessment = await _fresh(db, a.id)
        return await _portal_view(db, opened)


@respond_router.delete("/{token}/files/{file_id}", response_model=PortalView, summary="Remove an uploaded file")
async def portal_delete_file(token: str, file_id: uuid.UUID, request: Request) -> PortalView:
    from app.models.collab import StoredFile
    from app.services import storage

    async with await _portal_session(token) as db:
        opened = await _open(db, token, request, "delete_file")
        a = opened.assessment
        _require_editable(a)
        sf = await db.scalar(select(StoredFile).where(StoredFile.id == file_id, StoredFile.entity_type == "assessment_answer"))
        answer = next((x for x in a.answers if sf is not None and x.id == sf.entity_id), None)
        if sf is None or answer is None:
            raise HTTPException(status_code=404, detail="File not found")
        reopened = _reopened(a)
        if reopened is not None and answer.question_id not in reopened:
            raise HTTPException(status_code=409, detail=wf.REOPENED_ONLY)
        actor = portal.portal_actor(a.tenant_id, opened.link)
        if answer.review_state == REVIEW_RETURNED:
            # Removing the evidence the reviewer questioned is a change to the answer too.
            answer.review_state = REVIEW_PENDING
            answer.answered_by, answer.answered_at = actor.email[:255], datetime.now(timezone.utc)
        await db.delete(sf)
        storage.delete_object(sf.storage_key)
        await audit.record(db, actor=actor, action="respond_delete_file", entity_type="assessment", entity_id=a.id,
                           summary=f"Removed {sf.filename} on '{a.title}' through the respondent link",
                           changes={"file_id": str(sf.id)})
        await db.flush()
        opened.assessment = await _fresh(db, a.id)
        return await _portal_view(db, opened)


@respond_router.post("/{token}/submit", response_model=PortalView, summary="Submit the answers")
async def portal_submit(token: str, request: Request) -> PortalView:
    async with await _portal_session(token) as db:
        opened = await _open(db, token, request, "submit")
        a = opened.assessment
        _require_editable(a)
        actor = portal.portal_actor(a.tenant_id, opened.link)
        opened.assessment = await _submit(db, a, actor, submitted_by=actor.email)
        return await _portal_view(db, opened)


router.include_router(respond_router)
