"""AI Assist API — "Circular Intelligence" extraction workspace.

Runs an extraction over pasted text (SBP circular, policy, incident note or free text)
and stores it. The extraction logic lives inline in this file (no 5th module file):

* If an Anthropic key is configured — via ``settings.anthropic_api_key`` OR the
  ``ANTHROPIC_API_KEY`` environment variable — the Anthropic Messages API is called with
  ``httpx``. Any failure (missing dep, network, auth, parse) is caught and falls back to
  the heuristic. ``model_used`` is set to the model id on success.
* Otherwise a DETERMINISTIC pure-Python heuristic runs and ``model_used`` = "heuristic".

The request must NEVER crash: ``_extract`` always returns a result.
"""
from __future__ import annotations

import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.ai_assist import AiExtraction, AiExtractionType, AiJobStatus
from app.schemas.ai_assist import AiExtractionCreate, AiExtractionRead
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit as audit_log

router = APIRouter(tags=["ai assist"])

_READ = Depends(require("ai:read"))
_WRITE = Depends(require("ai:write"))

# Anthropic Messages API — used only when a key is configured; every failure falls back
# to the heuristic below so the request never crashes.
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_MODEL = "claude-sonnet-4-5"
_ANTHROPIC_VERSION = "2023-06-01"


# ============================================================= key resolution ===
def _anthropic_key() -> str | None:
    """Resolve an Anthropic key from settings first, then the environment.

    Neither must exist — when both are absent the module runs fully offline. ``settings``
    does not currently declare ``anthropic_api_key`` so ``getattr`` returns ``None`` and
    we fall through to the environment variable.
    """
    key = getattr(settings, "anthropic_api_key", None)
    if key:
        return str(key)
    env = os.environ.get("ANTHROPIC_API_KEY")
    return env or None


# ============================================================ offline heuristic ===
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+|\n+")
_OBLIGATION_RE = re.compile(
    r"\b(shall not|shall|must|required|mandatory|ensure|prohibited|comply|complied|"
    r"responsible for|obligated|obliged|no later than|within)\b",
    re.IGNORECASE,
)
_NUMDATE_RE = re.compile(r"\d")

# Keyword → ISO/IEC 27001:2022 Annex A control, for the offline control-mapping
# heuristic. 2022 numbering (A.5-A.8), not the retired 2013 A.9-A.18 domains, so the
# output names clauses that exist in the installed framework; every reference here is
# pinned to the library template by ``tests/test_clause_suggestions.py``. The synonym
# table in ``services.clause_suggestions`` is consulted too; this list adds the
# single-word cues it deliberately does not treat as a topic on their own.
_ISO_KEYWORDS: dict[str, str] = {
    "access control": "A.5.15",
    "least privilege": "A.8.2",
    "password": "A.5.17",
    "authentication": "A.8.5",
    "encryption": "A.8.24",
    "cryptograph": "A.8.24",
    "key management": "A.8.24",
    "physical": "A.7.1",
    "backup": "A.8.13",
    "logging": "A.8.15",
    "monitoring": "A.8.16",
    "malware": "A.8.7",
    "vulnerability": "A.8.8",
    "patch": "A.8.8",
    "network": "A.8.20",
    "transmission": "A.5.14",
    "supplier": "A.5.19",
    "third party": "A.5.19",
    "third-party": "A.5.19",
    "outsourc": "A.5.19",
    "cloud": "A.5.23",
    "incident": "A.5.24",
    "breach": "A.5.26",
    "continuity": "A.5.30",
    "disaster recovery": "A.5.30",
    "compliance": "A.5.31",
    "audit": "A.5.35",
    "retention": "A.5.33",
    "privacy": "A.5.34",
    "personal data": "A.5.34",
    "training": "A.6.3",
    "awareness": "A.6.3",
    "change management": "A.8.32",
    "change control": "A.8.32",
    "classification": "A.5.12",
}
#: AML/CFT programme elements — not ISO controls, reported alongside them.
_AML_KEYWORDS: dict[str, str] = {
    "customer due diligence": "AML/CFT — customer due diligence",
    "kyc": "AML/CFT — customer due diligence",
    "aml": "AML/CFT programme",
    "suspicious transaction": "AML/CFT — STR/SAR reporting",
}


def _iso_title(ref: str) -> str:
    from app.services.framework_library import TEMPLATES

    for r in TEMPLATES["iso-27001-2022"]["requirements"]:
        if r["reference"] == ref:
            return r["title"]
    return ""


def iso_controls_for_text(text: str) -> list[tuple[str, str]]:
    """ISO/IEC 27001:2022 Annex A (reference, title) pairs named or implied by ``text``:
    the synonym table's topics first (in order of mention), then keyword cues."""
    from app.services.clause_suggestions import iso_annex_a_for_text

    out = list(iso_annex_a_for_text(text))
    low = (text or "").lower()
    for kw, ref in _ISO_KEYWORDS.items():
        pair = (ref, _iso_title(ref))
        if kw in low and pair not in out:
            out.append(pair)
    return out


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_SPLIT.split(text or "") if p and p.strip()]


def _heuristic_obligations(text: str) -> str:
    hits = [s for s in _sentences(text) if _OBLIGATION_RE.search(s)]
    if not hits:
        return ("No explicit obligations detected. Review the source manually — no "
                "sentence contained obligation language (shall, must, required, "
                "mandatory, ensure, comply, prohibited).")
    return "\n".join(f"{i}. {s}" for i, s in enumerate(hits, 1))


def _heuristic_summary(text: str) -> str:
    sents = _sentences(text)
    if not sents:
        return "No content to summarise."
    out = " ".join(sents[:3])
    facts = [s for s in sents if _NUMDATE_RE.search(s)][:8]
    if facts:
        out += "\n\nKey figures & dates:\n" + "\n".join(f"- {s}" for s in facts)
    return out


def _key_nouns(text: str) -> list[str]:
    """A cheap proxy for the salient nouns/entities: capitalised words, then frequency."""
    stop = {"this", "that", "these", "those", "shall", "must", "the", "state", "bank"}
    seen: list[str] = []
    for w in re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text or ""):
        if w not in seen and w.lower() not in stop:
            seen.append(w)
    if len(seen) < 3:
        freq: dict[str, int] = defaultdict(int)
        for w in re.findall(r"\b[a-z]{5,}\b", (text or "").lower()):
            if w not in stop:
                freq[w] += 1
        for w in sorted(freq, key=lambda k: freq[k], reverse=True):
            cap = w.capitalize()
            if cap not in seen:
                seen.append(cap)
            if len(seen) >= 4:
                break
    return seen[:6] or ["the subject area"]


def _heuristic_risk_suggestions(text: str) -> str:
    nouns = _key_nouns(text)
    a = nouns[0]
    b = nouns[1] if len(nouns) > 1 else a
    c = nouns[2] if len(nouns) > 2 else a
    risks = [
        f"Risk of non-compliance with the requirements relating to {a}, leading to "
        f"regulatory censure, fines or supervisory action.",
        f"Risk that controls over {b} are inadequate or not evidenced, resulting in "
        f"operational, financial or reputational loss.",
        f"Risk that changes affecting {c} are not implemented within the mandated "
        f"timeline, causing a breach of the obligation.",
    ]
    return "\n".join(f"{i}. {r}" for i, r in enumerate(risks, 1))


def _heuristic_control_mapping(text: str) -> str:
    low = (text or "").lower()
    matched = [f"{ref} {title}" for ref, title in iso_controls_for_text(text)]
    for kw, element in _AML_KEYWORDS.items():
        if kw in low and element not in matched:
            matched.append(element)
    if not matched:
        return ("No ISO/IEC 27001:2022 Annex A controls or AML programme elements detected "
                "from the source text. Map controls manually.")
    return "\n".join(f"- {c}" for c in matched)


def _heuristic(extraction_type: AiExtractionType, text: str) -> str:
    if extraction_type == AiExtractionType.summary:
        return _heuristic_summary(text)
    if extraction_type == AiExtractionType.risk_suggestions:
        return _heuristic_risk_suggestions(text)
    if extraction_type == AiExtractionType.control_mapping:
        return _heuristic_control_mapping(text)
    return _heuristic_obligations(text)


# ============================================================ Anthropic (LLM) ===
_SYSTEM_PROMPTS: dict[AiExtractionType, str] = {
    AiExtractionType.obligations: (
        "You are a Pakistani banking compliance analyst. Extract every discrete "
        "regulatory obligation from the provided text (for example an SBP circular). "
        "Return a numbered list where each item is one clear, actionable obligation. Do "
        "not invent obligations that are not in the text."
    ),
    AiExtractionType.summary: (
        "You are a GRC analyst at a Pakistani bank. Summarise the provided document in "
        "3-4 sentences, then list the key dates, figures and deadlines as bullet points."
    ),
    AiExtractionType.risk_suggestions: (
        "You are a risk manager at a Pakistani bank. Based on the text, propose 3 "
        "concise, well-formed operational or compliance risk statements. Return a "
        "numbered list."
    ),
    AiExtractionType.control_mapping: (
        "You are an ISO 27001 practitioner. Identify which ISO/IEC 27001:2022 Annex A "
        "controls (A.5-A.8 numbering, e.g. 'A.8.5 Secure authentication'; never the "
        "2013 A.9-A.18 numbering) and AML/CFT programme elements, if relevant, the text "
        "relates to. Return a short bulleted list, one control per line, reference first."
    ),
}


async def _run_llm(key: str, extraction_type: AiExtractionType, title: str, input_text: str) -> str:
    """Call the Anthropic Messages API. Raises on any failure (caller handles fallback)."""
    import httpx  # FastAPI dependency; guarded so an import failure falls back to heuristic.

    system = _SYSTEM_PROMPTS.get(extraction_type, _SYSTEM_PROMPTS[AiExtractionType.obligations])
    user = f"Title: {title}\n\nSource text:\n\n{input_text}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": _ANTHROPIC_MODEL,
                "max_tokens": 1500,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
    resp.raise_for_status()
    data = resp.json()
    parts = data.get("content", []) or []
    text = "".join(
        p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
    ).strip()
    if not text:
        raise ValueError("empty response from model")
    return text


async def _extract(extraction_type: AiExtractionType, title: str, input_text: str) -> tuple[str, str, bool]:
    """Run the extraction. Returns (output_text, model_used, ok) and NEVER raises."""
    key = _anthropic_key()
    if key:
        try:
            out = await _run_llm(key, extraction_type, title, input_text)
            return out, _ANTHROPIC_MODEL, True
        except Exception:  # noqa: BLE001 — any LLM/network/parse failure falls back to heuristic.
            pass
    try:
        return _heuristic(extraction_type, input_text), "heuristic", True
    except Exception as exc:  # noqa: BLE001 — defensive; the heuristic is pure Python.
        return f"Extraction failed: {exc}", "heuristic", False


# ================================================================== helpers ===
async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, obj_id) -> AiExtraction:
    obj = await db.scalar(
        select(AiExtraction).where(AiExtraction.id == obj_id, AiExtraction.deleted.is_(False))
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return obj


# ================================================================== routes ===
@router.post("/ai-assist/extract", response_model=AiExtractionRead, status_code=201, dependencies=[_WRITE])
async def run_extraction(body: AiExtractionCreate, db: DbSession, user: CurrentUser) -> AiExtractionRead:
    output_text, model_used, ok = await _extract(body.extraction_type, body.title, body.input_text)
    obj = AiExtraction(
        tenant_id=user.tenant_id,
        title=body.title,
        source_type=body.source_type,
        extraction_type=body.extraction_type,
        input_text=body.input_text,
        output_text=output_text,
        model_used=model_used,
        status=AiJobStatus.completed if ok else AiJobStatus.failed,
        created_by=user.email,
    )
    obj.reference = await _next_ref(db, AiExtraction, "AI")
    db.add(obj)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="ai_extraction", entity_id=obj.id,
        summary=f"Ran {body.extraction_type.value} extraction {obj.reference} via {model_used}",
    )
    return AiExtractionRead.model_validate(obj)


_AI_SORTABLE = {
    "reference": AiExtraction.reference,
    "title": AiExtraction.title,
    "source_type": AiExtraction.source_type,
    "extraction_type": AiExtraction.extraction_type,
    "status": AiExtraction.status,
    "created_at": AiExtraction.created_at,
}


@router.get("/ai-assist", response_model=Page[AiExtractionRead], dependencies=[_READ])
async def list_extractions(
    db: DbSession,
    search: str | None = None,
    extraction_type: Annotated[AiExtractionType | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AiExtractionRead]:
    stmt = select(AiExtraction).where(AiExtraction.deleted.is_(False))
    if extraction_type is not None:
        stmt = stmt.where(AiExtraction.extraction_type == extraction_type)
    if search:
        stmt = stmt.where(
            AiExtraction.title.ilike(f"%{search}%") | AiExtraction.reference.ilike(f"%{search}%")
        )
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _AI_SORTABLE, default=AiExtraction.created_at)
    else:
        stmt = stmt.order_by(AiExtraction.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[AiExtractionRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/ai-assist/{eid}", response_model=AiExtractionRead, dependencies=[_READ])
async def get_extraction(eid: uuid.UUID, db: DbSession) -> AiExtractionRead:
    return AiExtractionRead.model_validate(await _get(db, eid))


@router.delete("/ai-assist/{eid}", status_code=204, dependencies=[_WRITE])
async def delete_extraction(eid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, eid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()


# ================================================================== summary ===
class AiTypeRow(BaseModel):
    extraction_type: str
    count: int
    ai_count: int          # produced by a real LLM
    heuristic_count: int   # produced by the offline heuristic


class AiSummary(BaseModel):
    rows: list[AiTypeRow]
    total: int
    ai_count: int
    heuristic_count: int


@router.get("/ai-assist-summary", response_model=AiSummary, dependencies=[_READ],
            summary="AI Assist usage roll-up by extraction type (real LLM vs heuristic)")
async def ai_summary(db: DbSession) -> AiSummary:
    rows_db = (await db.scalars(select(AiExtraction).where(AiExtraction.deleted.is_(False)))).all()
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "ai": 0, "heuristic": 0})
    for e in rows_db:
        g = groups[e.extraction_type.value]
        g["count"] += 1
        if (e.model_used or "heuristic") == "heuristic":
            g["heuristic"] += 1
        else:
            g["ai"] += 1
    rows = [
        AiTypeRow(extraction_type=k, count=v["count"], ai_count=v["ai"], heuristic_count=v["heuristic"])
        for k, v in sorted(groups.items())
    ]
    return AiSummary(
        rows=rows,
        total=sum(r.count for r in rows),
        ai_count=sum(r.ai_count for r in rows),
        heuristic_count=sum(r.heuristic_count for r in rows),
    )


# ============================================================ structured mapping ===
class ControlMappingRequest(BaseModel):
    """Either a control (its name, description and objective are used, and clauses it
    already meets are left out) or free text to map."""

    control_id: uuid.UUID | None = None
    title: str = ""
    text: str = ""
    limit: int = 10


class IsoControlRef(BaseModel):
    reference: str
    title: str


class ControlMappingResult(BaseModel):
    #: "control" when a control id was given, else "text".
    source: str
    control_id: uuid.UUID | None = None
    #: Clauses of the installed compliance frameworks, ranked — the same engine and
    #: shape as ``GET /controls/{id}/suggested-requirements``, so a UI can accept them.
    suggestions: list[dict]
    #: ISO/IEC 27001:2022 Annex A controls the text names, installed or not.
    iso_controls: list[IsoControlRef]
    #: The same as a readable list (what the stored heuristic extraction contains).
    output_text: str


@router.post(
    "/ai-assist/control-mapping", response_model=ControlMappingResult, dependencies=[_READ],
    summary="Structured control → requirement mapping (offline, deterministic)",
)
async def control_mapping_suggestions(
    body: ControlMappingRequest, db: DbSession, user: CurrentUser,
) -> ControlMappingResult:
    """Map a control, or a piece of text, to framework clauses as **links**, not prose.

    With ``control_id`` this is the clause-suggestion engine for that control
    (requires ``control:read`` as well). With text, the text is scored as if it were a
    control's description against the installed compliance frameworks. Nothing is
    stored; accept suggestions through ``/controls/{id}/suggested-requirements/accept``.
    """
    from app.models.control import Control
    from app.services import clause_suggestions as engine

    limit = max(1, min(body.limit, 50))
    if body.control_id is not None:
        if "control:read" not in set(user.permission_codes):
            raise HTTPException(status_code=403, detail="Requires permission(s): control:read")
        control = await db.scalar(
            select(Control).where(Control.id == body.control_id, Control.deleted.is_(False))
        )
        if control is None:
            raise HTTPException(status_code=404, detail="Control not found")
        found = (await engine.suggest_for_controls(db, [control], limit=limit, min_score=0.2))[control.id]
        text = "\n".join(p for p in (control.name, control.description, control.objective) if p)
        source = "control"
    else:
        text = f"{body.title}\n{body.text}".strip()
        if not text:
            raise HTTPException(status_code=422, detail="Give a control_id or some text to map")
        index = await engine.load_index(db)
        found = engine.score_candidates(
            engine.ControlText(name=body.title, description=body.text), index,
            limit=limit, min_score=0.2,
        )
        source = "text"
    iso = [IsoControlRef(reference=r, title=t) for r, t in iso_controls_for_text(text)]
    return ControlMappingResult(
        source=source,
        control_id=body.control_id,
        suggestions=[
            {**s.as_dict(), "requirement_id": str(s.requirement_id),
             "framework_id": str(s.framework_id) if s.framework_id else None}
            for s in found
        ],
        iso_controls=iso,
        output_text=_heuristic_control_mapping(text),
    )
