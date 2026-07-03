"""Collaboration API — comments, tags and attachments for any record.

All endpoints are authentication-only (any member can collaborate). Comments and
attachments may be removed by their author or an admin (``role:write``).
"""
from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.collab import Attachment, Comment, EntityTag, StoredFile, Tag
from app.schemas.collab import (
    AttachmentCreate,
    AttachmentRead,
    CollabBundle,
    CommentCreate,
    CommentRead,
    StoredFileRead,
    TagAssign,
    TagCreate,
    TagRead,
)
from app.services import storage

router = APIRouter(prefix="/collab", tags=["collaboration"])


def _is_admin(user) -> bool:
    return "role:write" in user.permission_codes


async def _tags_for(db, entity_type: str, entity_id: uuid.UUID) -> list[Tag]:
    rows = (
        await db.scalars(
            select(Tag)
            .join(EntityTag, EntityTag.tag_id == Tag.id)
            .where(EntityTag.entity_type == entity_type, EntityTag.entity_id == entity_id)
            .order_by(Tag.name)
        )
    ).all()
    return list(rows)


@router.get("/tags", response_model=list[TagRead])
async def tag_library(db: DbSession, _: CurrentUser) -> list[TagRead]:
    rows = (await db.scalars(select(Tag).order_by(Tag.name))).all()
    return [TagRead.model_validate(t) for t in rows]


@router.post("/tags", response_model=TagRead, status_code=201)
async def create_tag(body: TagCreate, db: DbSession, user: CurrentUser) -> TagRead:
    existing = await db.scalar(select(Tag).where(Tag.name == body.name))
    if existing:
        return TagRead.model_validate(existing)
    tag = Tag(tenant_id=user.tenant_id, name=body.name, color=body.color)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return TagRead.model_validate(tag)


@router.get("/{entity_type}/{entity_id}", response_model=CollabBundle)
async def get_bundle(entity_type: str, entity_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CollabBundle:
    comments = (
        await db.scalars(
            select(Comment)
            .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
            .order_by(Comment.created_at)
        )
    ).all()
    attachments = (
        await db.scalars(
            select(Attachment)
            .where(Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
            .order_by(Attachment.created_at)
        )
    ).all()
    files = (
        await db.scalars(
            select(StoredFile)
            .where(StoredFile.entity_type == entity_type, StoredFile.entity_id == entity_id)
            .order_by(StoredFile.created_at)
        )
    ).all()
    tags = await _tags_for(db, entity_type, entity_id)
    available = (await db.scalars(select(Tag).order_by(Tag.name))).all()

    admin = _is_admin(user)
    crs = []
    for c in comments:
        cr = CommentRead.model_validate(c)
        cr.can_delete = admin or c.author_id == user.id
        crs.append(cr)
    frs = []
    for f in files:
        fr = StoredFileRead.model_validate(f)
        fr.can_delete = admin or f.uploaded_by_email == user.email
        frs.append(fr)
    return CollabBundle(
        comments=crs,
        tags=[TagRead.model_validate(t) for t in tags],
        attachments=[AttachmentRead.model_validate(a) for a in attachments],
        files=frs,
        available_tags=[TagRead.model_validate(t) for t in available],
    )


@router.post("/{entity_type}/{entity_id}/comments", response_model=CommentRead, status_code=201)
async def add_comment(
    entity_type: str, entity_id: uuid.UUID, body: CommentCreate, db: DbSession, user: CurrentUser
) -> CommentRead:
    c = Comment(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=user.id,
        author_email=user.email,
        body=body.body,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    cr = CommentRead.model_validate(c)
    cr.can_delete = True
    return cr


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    c = await db.scalar(select(Comment).where(Comment.id == comment_id))
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if not (_is_admin(user) or c.author_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your comment")
    await db.delete(c)


@router.post("/{entity_type}/{entity_id}/attachments", response_model=AttachmentRead, status_code=201)
async def add_attachment(
    entity_type: str, entity_id: uuid.UUID, body: AttachmentCreate, db: DbSession, user: CurrentUser
) -> AttachmentRead:
    a = Attachment(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        added_by_email=user.email,
        **body.model_dump(),
    )
    db.add(a)
    await db.flush()
    await db.refresh(a)
    return AttachmentRead.model_validate(a)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(attachment_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    a = await db.scalar(select(Attachment).where(Attachment.id == attachment_id))
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not (_is_admin(user) or a.added_by_email == user.email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your attachment")
    await db.delete(a)


# --------------------------------------------------------------- uploaded files ---
@router.post("/{entity_type}/{entity_id}/files", response_model=StoredFileRead, status_code=201)
async def upload_file(
    entity_type: str,
    entity_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> StoredFileRead:
    """Upload a binary file (evidence, screenshot, PDF…) and attach it to a record."""
    blob = await storage.save_upload(user.tenant_id, file)
    sf = StoredFile(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        title=blob.filename,
        filename=blob.filename,
        content_type=blob.content_type,
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        storage_key=blob.storage_key,
        uploaded_by_email=user.email,
    )
    db.add(sf)
    await db.flush()
    await db.refresh(sf)
    fr = StoredFileRead.model_validate(sf)
    fr.can_delete = True
    return fr


@router.get("/files/{file_id}/download")
async def download_file(file_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FileResponse:
    sf = await db.scalar(select(StoredFile).where(StoredFile.id == file_id))
    if sf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    path = storage.resolve_path(user.tenant_id, sf.storage_key)
    return FileResponse(
        path,
        media_type=sf.content_type or "application/octet-stream",
        filename=sf.filename,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(sf.filename)}"
        },
    )


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    sf = await db.scalar(select(StoredFile).where(StoredFile.id == file_id))
    if sf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not (_is_admin(user) or sf.uploaded_by_email == user.email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your file")
    storage.delete_object(sf.storage_key)
    await db.delete(sf)


@router.post("/{entity_type}/{entity_id}/tags", response_model=list[TagRead], status_code=201)
async def assign_tag(
    entity_type: str, entity_id: uuid.UUID, body: TagAssign, db: DbSession, user: CurrentUser
) -> list[TagRead]:
    tag_id = body.tag_id
    if tag_id is None:
        if not body.name:
            raise HTTPException(status_code=422, detail="Provide tag_id or name")
        tag = await db.scalar(select(Tag).where(Tag.name == body.name))
        if tag is None:
            tag = Tag(tenant_id=user.tenant_id, name=body.name, color=body.color)
            db.add(tag)
            await db.flush()
        tag_id = tag.id
    exists = await db.scalar(
        select(EntityTag).where(
            EntityTag.tag_id == tag_id,
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    )
    if exists is None:
        db.add(EntityTag(tenant_id=user.tenant_id, tag_id=tag_id, entity_type=entity_type, entity_id=entity_id))
        await db.flush()
    return [TagRead.model_validate(t) for t in await _tags_for(db, entity_type, entity_id)]


@router.delete("/{entity_type}/{entity_id}/tags/{tag_id}", status_code=204)
async def unassign_tag(
    entity_type: str, entity_id: uuid.UUID, tag_id: uuid.UUID, db: DbSession, _: CurrentUser
) -> None:
    et = await db.scalar(
        select(EntityTag).where(
            EntityTag.tag_id == tag_id,
            EntityTag.entity_type == entity_type,
            EntityTag.entity_id == entity_id,
        )
    )
    if et is not None:
        await db.delete(et)
