import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_service import service
from doc_service.config import settings
from doc_service.db import get_db
from doc_service.models import Document, DocumentKind
from doc_service.schemas import (
    DocumentDetail,
    DocumentList,
    DocumentRead,
    EmbedRequest,
    EmbedResponse,
    InternalDocumentText,
    SearchRequest,
    SearchResponse,
    UpdateDocument,
    UploadResult,
)
from shared.auth import Principal, build_auth_dependency, build_internal_dependency
from shared.errors import NotFoundError

principal_dep = build_auth_dependency(settings)
internal_dep = build_internal_dependency(settings)

router = APIRouter(prefix="/documents", tags=["documents"])
internal_router = APIRouter(
    prefix="/internal", tags=["internal"], dependencies=[Depends(internal_dep)]
)


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form(DocumentKind.OTHER),
    title: str | None = Form(None),
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> UploadResult:
    """Upload, parse, chunk and index one application document."""
    if kind not in DocumentKind.ALL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of: {', '.join(DocumentKind.ALL)}",
        )

    data = await file.read()
    document, warnings = await service.ingest(
        db,
        user_key=principal.user_key,
        data=data,
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        kind=kind,
        title=title,
    )
    return UploadResult(document=DocumentRead.model_validate(document), warnings=warnings)


@router.get("", response_model=DocumentList)
def list_documents(
    kind: str | None = None,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> DocumentList:
    statement = (
        select(Document)
        .where(Document.user_key == principal.user_key)
        .order_by(Document.created_at.desc())
    )
    if kind:
        statement = statement.where(Document.kind == kind)
    rows = list(db.scalars(statement).all())
    return DocumentList(items=[DocumentRead.model_validate(row) for row in rows], total=len(rows))


@router.get("/stats")
def document_stats(
    principal: Principal = Depends(principal_dep), db: Session = Depends(get_db)
) -> dict:
    return service.stats(db, principal.user_key)


@router.get("/{document_id}", response_model=DocumentDetail)
def read_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    return DocumentDetail.model_validate(service.get_owned(db, document_id, principal.user_key))


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: uuid.UUID,
    payload: UpdateDocument,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> DocumentRead:
    document = service.get_owned(db, document_id, principal.user_key)
    if payload.kind is not None:
        if payload.kind not in DocumentKind.ALL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown kind"
            )
        document.kind = payload.kind
    if payload.title is not None:
        document.title = payload.title[:500]
    db.flush()
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/reindex", response_model=DocumentRead)
async def reindex_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> DocumentRead:
    """Re-chunk and re-embed from the stored original, after a settings change."""
    document = service.get_owned(db, document_id, principal.user_key)
    await service.index_document(db, document)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> None:
    service.delete_document(db, service.get_owned(db, document_id, principal.user_key))


# ---------------------------------------------------------------- internal


@internal_router.post("/search", response_model=SearchResponse)
async def internal_search(payload: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    """Retrieval for rag-service and eval-service.

    Takes a raw query rather than a vector: embedding lives here and only here,
    so changing provider touches one service.
    """
    hits = await service.search(
        db,
        user_key=payload.user_key,
        query=payload.query,
        top_k=payload.top_k,
        document_ids=payload.document_ids or None,
        kinds=payload.kinds or None,
        max_distance=payload.max_distance,
    )
    return SearchResponse(hits=hits, query=payload.query, embedding_model=service.embeddings.model)


@internal_router.post("/embed", response_model=EmbedResponse)
async def internal_embed(payload: EmbedRequest) -> EmbedResponse:
    vectors = await service.embeddings.embed(payload.texts)
    return EmbedResponse(
        vectors=vectors,
        model=service.embeddings.model,
        dimensions=service.embeddings.dimensions,
    )


@internal_router.get("/documents/{document_id}/text", response_model=InternalDocumentText)
def internal_document_text(
    document_id: uuid.UUID, user_key: str, db: Session = Depends(get_db)
) -> InternalDocumentText:
    """Full text for evaluation.

    eval-service reads whole documents rather than retrieved chunks: judging an
    SOP's structure requires seeing all of it, not the parts nearest a query.
    `user_key` is still required so an internal caller cannot walk the table.
    """
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.user_key == user_key)
    )
    if document is None:
        raise NotFoundError("Document not found")
    return InternalDocumentText.model_validate(document)


@internal_router.get("/documents", response_model=DocumentList)
def internal_list_documents(
    user_key: str, kind: str | None = None, db: Session = Depends(get_db)
) -> DocumentList:
    statement = (
        select(Document).where(Document.user_key == user_key).order_by(Document.created_at.desc())
    )
    if kind:
        statement = statement.where(Document.kind == kind)
    rows = list(db.scalars(statement).all())
    return DocumentList(items=[DocumentRead.model_validate(row) for row in rows], total=len(rows))
