import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rag_service import agent
from rag_service.config import settings
from rag_service.db import get_db
from rag_service.models import Citation, Conversation, InputMode, Message, Role, WebSource
from rag_service.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationList,
    ConversationRead,
    CreateConversation,
    MessageRead,
    RefineEmailRequest,
    RefineEmailResponse,
    UpdateConversation,
)
from shared.auth import Principal, build_auth_dependency
from shared.errors import NotFoundError

principal_dep = build_auth_dependency(settings)
router = APIRouter(tags=["chat"])


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    return header.removeprefix("Bearer ").strip() or None


def _load(db: Session, conversation_id: uuid.UUID, user_key: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .options(
            selectinload(Conversation.messages).selectinload(Message.citations),
            selectinload(Conversation.messages).selectinload(Message.web_sources),
        )
        .where(Conversation.id == conversation_id, Conversation.user_key == user_key)
    )
    if conversation is None:
        raise NotFoundError("Conversation not found")
    return conversation


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """One grounded turn: plan queries, retrieve, answer with citations."""
    token = _bearer(request)
    question = payload.message.strip()

    if payload.conversation_id:
        conversation = _load(db, payload.conversation_id, principal.user_key)
        if payload.document_ids:
            conversation.document_ids = payload.document_ids
    else:
        conversation = Conversation(
            user_key=principal.user_key,
            title=await agent.generate_title(question),
            document_ids=payload.document_ids,
            opportunity_id=payload.opportunity_id,
            opportunity_title=(payload.opportunity or {}).get("title"),
        )
        db.add(conversation)
        db.flush()

    user_message = Message(
        conversation_id=conversation.id,
        role=Role.USER,
        content=question,
        input_mode=(
            InputMode.VOICE
            if payload.voice or payload.input_mode == InputMode.VOICE
            else InputMode.TEXT
        ),
    )
    db.add(user_message)
    db.flush()
    # Append so the history the agent reads includes this turn's context.
    conversation.messages.append(user_message)

    outcome = await agent.retrieve(
        user_key=principal.user_key,
        question=question,
        conversation=conversation,
        user_token=token,
    )
    assistant_message, hits, web_sources = await agent.answer(
        question=question,
        conversation=conversation,
        outcome=outcome,
        reasoning=payload.reasoning,
        voice=payload.voice,
        web=payload.web,
        opportunity=payload.opportunity,
    )
    db.add(assistant_message)
    db.flush()

    for position, hit in enumerate(hits, start=1):
        db.add(
            Citation(
                message_id=assistant_message.id,
                position=position,
                document_id=uuid.UUID(hit["document_id"]),
                chunk_id=uuid.UUID(hit["chunk_id"]),
                document_title=hit["document_title"][:500],
                document_kind=hit["document_kind"],
                page_number=hit.get("page_number"),
                section=hit.get("section"),
                excerpt=hit["content"][:2000],
                score=round(1.0 - float(hit["distance"]), 4),
            )
        )

    for position, source in enumerate(web_sources, start=1):
        db.add(
            WebSource(
                message_id=assistant_message.id,
                position=position,
                title=source.title,
                url=source.url,
                excerpt=(source.content or None),
            )
        )

    db.flush()
    db.refresh(assistant_message)

    return ChatResponse(
        conversation_id=conversation.id,
        title=conversation.title,
        user_message=MessageRead.model_validate(user_message),
        assistant_message=MessageRead.model_validate(assistant_message),
    )


@router.get("/conversations", response_model=ConversationList)
def list_conversations(
    include_archived: bool = False,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> ConversationList:
    statement = (
        select(Conversation)
        .where(Conversation.user_key == principal.user_key)
        .order_by(Conversation.updated_at.desc())
    )
    if not include_archived:
        statement = statement.where(Conversation.archived.is_(False))
    rows = list(db.scalars(statement).all())
    total = (
        db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_key == principal.user_key)
        )
        or 0
    )
    return ConversationList(
        items=[ConversationRead.model_validate(row) for row in rows], total=total
    )


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CreateConversation,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> ConversationRead:
    conversation = Conversation(
        user_key=principal.user_key,
        title=payload.title or "New conversation",
        document_ids=payload.document_ids,
    )
    db.add(conversation)
    db.flush()
    return ConversationRead.model_validate(conversation)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def read_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    return ConversationDetail.model_validate(_load(db, conversation_id, principal.user_key))


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: UpdateConversation,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> ConversationRead:
    conversation = _load(db, conversation_id, principal.user_key)
    if payload.title is not None:
        conversation.title = payload.title[:300]
    if payload.document_ids is not None:
        conversation.document_ids = payload.document_ids
    if payload.archived is not None:
        conversation.archived = payload.archived
    db.flush()
    return ConversationRead.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> None:
    db.delete(_load(db, conversation_id, principal.user_key))


@router.post("/compose/refine-email", response_model=RefineEmailResponse)
async def refine_email(
    payload: RefineEmailRequest,
    request: Request,
    principal: Principal = Depends(principal_dep),
) -> RefineEmailResponse:
    """Sharpen a drafted enquiry to an opportunity contact.

    Lives here rather than in core-api because this is the service that already
    holds the model client and can reach the applicant's own documents — which
    is what lets the rewrite tighten a claim without inventing a credential.
    """
    applicant_context: str | None = None
    if payload.ground_in_documents:
        try:
            response = await agent.docs.post(
                "/internal/search",
                json={
                    "user_key": principal.user_key,
                    "query": (
                        f"{(payload.opportunity or {}).get('title', '')} "
                        "relevant experience skills motivation background"
                    ).strip(),
                    "top_k": 5,
                    "max_distance": 0.8,
                },
                user_token=_bearer(request),
            )
            excerpts = [hit["content"] for hit in response.get("hits", [])]
            if excerpts:
                applicant_context = "\n\n".join(excerpts)[:6000]
        except Exception:
            # Refinement without their documents is still useful; it just cannot
            # tighten specifics.
            applicant_context = None

    result = await agent.refine_email(
        subject=payload.subject,
        body=payload.body,
        opportunity=payload.opportunity,
        contact_name=payload.contact_name,
        applicant_context=applicant_context,
    )
    return RefineEmailResponse(**result)
