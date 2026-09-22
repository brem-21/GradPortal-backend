import json
import time
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rag_service import agent
from rag_service.config import settings
from rag_service.db import SessionLocal, get_db
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
log = structlog.get_logger(__name__)
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
            InputMode.VOICE if payload.input_mode == InputMode.VOICE else InputMode.TEXT
        ),
    )
    db.add(user_message)
    db.flush()
    # Append so the history the agent reads includes this turn's context.
    conversation.messages.append(user_message)

    outcome = (
        await agent.retrieve(
            user_key=principal.user_key,
            question=question,
            conversation=conversation,
            user_token=token,
        )
        if payload.use_documents
        else agent.RetrievalOutcome(has_documents=False)
    )
    assistant_message, hits, web_sources = await agent.answer(
        question=question,
        conversation=conversation,
        outcome=outcome,
        reasoning=payload.reasoning,
        web=payload.web,
        opportunity=payload.opportunity,
        use_documents=payload.use_documents,
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


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(principal_dep),
) -> StreamingResponse:
    """The same turn as /chat, streamed.

    Retrieval happens before the first token, so citations can be shown while
    the answer is still being written — the reader sees what it is drawing on
    rather than waiting for the whole thing to land.

    A separate session is opened inside the generator: the request-scoped one
    is closed when this function returns, which is before any of the streaming
    work has run.
    """
    token = _bearer(request)
    question = payload.message.strip()
    user_key = principal.user_key

    async def events() -> AsyncIterator[str]:
        db = SessionLocal()
        started = time.perf_counter()
        try:
            needs_title = False
            if payload.conversation_id:
                conversation = db.scalar(
                    select(Conversation)
                    .options(selectinload(Conversation.messages))
                    .where(
                        Conversation.id == payload.conversation_id,
                        Conversation.user_key == user_key,
                    )
                )
                if conversation is None:
                    yield _sse({"type": "error", "detail": "Conversation not found"})
                    return
                if payload.document_ids:
                    conversation.document_ids = payload.document_ids
            else:
                # A provisional title now, the real one after the answer:
                # naming the thread is an LLM round-trip, and putting it before
                # retrieval delays the first token for something the reader is
                # not yet looking at.
                conversation = Conversation(
                    user_key=user_key,
                    title=question[:80],
                    document_ids=payload.document_ids,
                    opportunity_id=payload.opportunity_id,
                    opportunity_title=(payload.opportunity or {}).get("title"),
                )
                db.add(conversation)
                db.flush()
                needs_title = True

            yield _sse(
                {
                    "type": "conversation",
                    "id": str(conversation.id),
                    "title": conversation.title,
                }
            )

            user_message = Message(
                conversation_id=conversation.id,
                role=Role.USER,
                content=question,
                input_mode=(
                    InputMode.VOICE
                    if payload.input_mode == InputMode.VOICE
                    else InputMode.TEXT
                ),
            )
            db.add(user_message)
            db.flush()
            conversation.messages.append(user_message)

            if payload.use_documents:
                yield _sse({"type": "status", "stage": "retrieving"})
                outcome = await agent.retrieve(
                    user_key=user_key,
                    question=question,
                    conversation=conversation,
                    user_token=token,
                )
            else:
                # The reader turned the dossier off; skip retrieval entirely
                # rather than fetching context that will not be used.
                outcome = agent.RetrievalOutcome(has_documents=False)

            messages, hits, grounded = agent.build_messages(
                question=question,
                conversation=conversation,
                outcome=outcome,
                web=payload.web,
                opportunity=payload.opportunity,
                use_documents=payload.use_documents,
            )

            # Show the evidence before the prose that rests on it.
            if hits:
                yield _sse(
                    {
                        "type": "citations",
                        "items": [
                            {
                                "position": index,
                                "document_id": hit["document_id"],
                                "document_title": hit["document_title"],
                                "document_kind": hit["document_kind"],
                                "page_number": hit.get("page_number"),
                                "section": hit.get("section"),
                                "excerpt": hit["content"][:600],
                                "score": round(1.0 - float(hit["distance"]), 4),
                            }
                            for index, hit in enumerate(hits, start=1)
                        ],
                    }
                )
            yield _sse(
                {
                    "type": "status",
                    "stage": "searching_web" if payload.web else "answering",
                    "grounded": grounded,
                    "queries": outcome.queries,
                }
            )

            answer_parts: list[str] = []
            reasoning_parts: list[str] = []
            web_sources: list[dict] = []
            model_used: str | None = None

            try:
                async for event in agent.llm.chat_stream(
                    messages,
                    reasoning=payload.reasoning,
                    temperature=0.2,
                    max_tokens=2000,
                    web_search=payload.web,
                ):
                    kind = event.get("type")
                    if kind == "content":
                        answer_parts.append(event["text"])
                        yield _sse({"type": "token", "text": event["text"]})
                    elif kind == "reasoning":
                        reasoning_parts.append(event["text"])
                        yield _sse({"type": "reasoning", "text": event["text"]})
                    elif kind == "citations":
                        web_sources = event["items"]
                        yield _sse({"type": "web", "items": web_sources})
                    elif kind == "done":
                        model_used = event.get("model")
            except Exception as exc:
                log.warning("stream_failed", error=str(exc))
                yield _sse({"type": "error", "detail": str(exc)[:400]})
                db.rollback()
                return

            content = "".join(answer_parts).strip()
            latency_ms = int((time.perf_counter() - started) * 1000)

            assistant_message = Message(
                conversation_id=conversation.id,
                role=Role.ASSISTANT,
                content=content,
                used_reasoning=payload.reasoning,
                reasoning=("".join(reasoning_parts))[:20000] or None,
                search_queries=outcome.queries,
                grounded=grounded,
                used_web=payload.web,
                model=model_used,
                latency_ms=latency_ms,
                meta={
                    "retrieval_rounds": outcome.rounds,
                    "hits_considered": len(outcome.hits),
                    "streamed": True,
                },
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
                        title=source["title"][:300],
                        url=source["url"],
                    )
                )

            db.commit()

            if needs_title:
                try:
                    conversation.title = await agent.generate_title(question)
                    db.commit()
                    yield _sse(
                        {
                            "type": "conversation",
                            "id": str(conversation.id),
                            "title": conversation.title,
                        }
                    )
                except Exception:
                    db.rollback()  # the provisional title is good enough

            yield _sse(
                {
                    "type": "done",
                    "message_id": str(assistant_message.id),
                    "conversation_id": str(conversation.id),
                    "latency_ms": latency_ms,
                    "model": model_used,
                    "grounded": grounded,
                }
            )
        except Exception as exc:  # noqa: BLE001 — the stream must always close cleanly
            log.exception("chat_stream_failed")
            db.rollback()
            yield _sse({"type": "error", "detail": str(exc)[:400]})
        finally:
            db.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx buffers SSE by default, which defeats the point.
            "X-Accel-Buffering": "no",
        },
    )
