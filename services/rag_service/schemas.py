import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    document_title: str
    document_kind: str
    page_number: int | None
    section: str | None
    excerpt: str
    score: float


class WebSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    title: str
    url: str
    excerpt: str | None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    input_mode: str
    used_reasoning: bool
    reasoning: str | None
    search_queries: list[str]
    grounded: bool
    model: str | None
    latency_ms: int | None
    created_at: datetime
    used_web: bool = False
    citations: list[CitationRead] = Field(default_factory=list)
    web_sources: list[WebSourceRead] = Field(default_factory=list)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_ids: list[uuid.UUID]
    opportunity_id: uuid.UUID | None = None
    opportunity_title: str | None = None
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)


class ConversationList(BaseModel):
    items: list[ConversationRead]
    total: int


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    # Routes to the reasoning model instead of the fast one.
    reasoning: bool = False
    # Live web search for this turn. Opt-in: it costs roughly 3500x a plain call.
    web: bool = False
    # Ground the answer in the user's own dossier. On by default — answering
    # from someone's own documents is the point of the feature, and making
    # them opt in every time would be a tax on the common case.
    use_documents: bool = True
    # How the question arrived. Recorded on the turn; it no longer changes
    # the answer, since there is no text-to-speech to shape it for.
    input_mode: str = "text"
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    # Pins the conversation to one posting so every turn has it in context.
    opportunity_id: uuid.UUID | None = None
    opportunity: dict | None = Field(
        default=None,
        description="Denormalised opportunity, passed by the caller that already has it.",
    )


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    title: str
    user_message: MessageRead
    assistant_message: MessageRead


class CreateConversation(BaseModel):
    title: str | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    opportunity_id: uuid.UUID | None = None
    opportunity_title: str | None = None


class RefineEmailRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=20, max_length=20000)
    contact_name: str | None = None
    opportunity: dict | None = None
    # Retrieval query used to pull supporting lines from the applicant's own
    # documents, so the rewrite can tighten a claim without inventing one.
    ground_in_documents: bool = True


class RefineEmailResponse(BaseModel):
    subject: str
    body: str
    changes: list[str]
    warnings: list[str]
    model: str


class UpdateConversation(BaseModel):
    title: str | None = None
    document_ids: list[uuid.UUID] | None = None
    archived: bool | None = None
