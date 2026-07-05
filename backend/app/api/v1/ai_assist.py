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
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.models.ai_assist import AiExtraction, AiExtractionType, AiJobStatus
from app.schemas.ai_assist import AiExtractionCreate, AiExtractionRead
from app.schemas.common import Page
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

# ISO 27001-ish (Annex A) + AML keyword → control domain mapping for control_mapping.
_ISO_KEYWORDS: dict[str, str] = {
    "access control": "A.9 Access control",
    "password": "A.9 Access control",
    "authentication": "A.9 Access control",
    "least privilege": "A.9 Access control",
    "encryption": "A.10 Cryptography",
    "cryptograph": "A.10 Cryptography",
    "key management": "A.10 Cryptography",
    "physical": "A.11 Physical & environmental security",
    "backup": "A.12 Operations security",
    "logging": "A.12 Operations security",
    "malware": "A.12 Operations security",
    "vulnerability": "A.12 Operations security",
    "patch": "A.12 Operations security",
    "network": "A.13 Communications security",
    "transmission": "A.13 Communications security",
    "supplier": "A.15 Supplier relationships",
    "third party": "A.15 Supplier relationships",
    "third-party": "A.15 Supplier relationships",
    "outsourc": "A.15 Supplier relationships",
    "incident": "A.16 Information security incident management",
    "breach": "A.16 Information security incident management",
    "continuity": "A.17 Business continuity",
    "disaster recovery": "A.17 Business continuity",
    "compliance": "A.18 Compliance",
    "audit": "A.18 Compliance",
    "retention": "A.18 Compliance",
    "customer due diligence": "AML/CFT — customer due diligence",
    "kyc": "AML/CFT — customer due diligence",
    "aml": "AML/CFT programme",
    "suspicious transaction": "AML/CFT — STR/SAR reporting",
}


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
    matched: list[str] = []
    for kw, ctrl in _ISO_KEYWORDS.items():
        if kw in low and ctrl not in matched:
            matched.append(ctrl)
    if not matched:
        return ("No ISO 27001 / AML control domains detected from the source text. Map "
                "controls manually.")
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
        "You are an ISO 27001 practitioner. Identify which ISO 27001 Annex A control "
        "domains (and AML/CFT programme elements, if relevant) the text relates to. "
        "Return a short bulleted list of control domains, one per line."
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
    count = await db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:03d}"


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


@router.get("/ai-assist", response_model=Page[AiExtractionRead], dependencies=[_READ])
async def list_extractions(
    db: DbSession,
    extraction_type: Annotated[AiExtractionType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AiExtractionRead]:
    stmt = select(AiExtraction).where(AiExtraction.deleted.is_(False))
    if extraction_type is not None:
        stmt = stmt.where(AiExtraction.extraction_type == extraction_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(
        stmt.order_by(AiExtraction.created_at.desc()).limit(limit).offset(offset)
    )).all()
    return Page(items=[AiExtractionRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/ai-assist/{eid}", response_model=AiExtractionRead, dependencies=[_READ])
async def get_extraction(eid: uuid.UUID, db: DbSession) -> AiExtractionRead:
    return AiExtractionRead.model_validate(await _get(db, eid))


@router.delete("/ai-assist/{eid}", status_code=204, dependencies=[_WRITE])
async def delete_extraction(eid: uuid.UUID, db: DbSession) -> None:
    obj = await _get(db, eid)
    obj.deleted = True
    obj.deleted_date = date.today()
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
