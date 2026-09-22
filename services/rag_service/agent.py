"""The agentic retrieval loop.

'Agentic' here means the assistant decides what to look for rather than
embedding the raw question: it plans queries from the conversation, judges
whether what came back is enough, and searches again with different phrasing if
it is not. It stops at two rounds — an unbounded loop mostly burns tokens
re-finding the same chunks.
"""

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field

import structlog

from rag_service.config import settings
from rag_service.models import Conversation, Message, Role
from rag_service.prompts import (
    EMAIL_REFINE,
    GENERAL_ONLY,
    GROUNDED_ANSWER,
    NO_CONTEXT,
    NO_DOCUMENTS,
    OPPORTUNITY_CONTEXT,
    QUERY_PLANNER,
    TITLE_PROMPT,
    VOICE_HINT,
    WEB_ENABLED,
    WEB_ONLY,
    build_context_block,
    describe_opportunity,
)
from shared.errors import UpstreamError
from shared.http import ServiceClient
from shared.llm import OpenRouterClient, extract_json

log = structlog.get_logger(__name__)

llm = OpenRouterClient(settings)
docs = ServiceClient(settings.doc_service_url, settings.internal_service_token, "doc-service")


@dataclass
class RetrievalOutcome:
    hits: list[dict] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    rounds: int = 0
    has_documents: bool = True

    @property
    def strong_hits(self) -> int:
        return sum(1 for hit in self.hits if hit["distance"] <= settings.strong_hit_distance)

    @property
    def is_sufficient(self) -> bool:
        """Whether there is anything worth showing the model.

        Deliberately just "did we find anything": the grounding prompt already
        requires the model to say when the excerpts do not answer the question,
        and it can judge that from the text far better than a distance cutoff
        can. Gating here on a distance floor made the assistant refuse
        questions its own documents plainly answered.
        """
        return bool(self.hits)


def _history(conversation: Conversation, limit: int) -> list[dict[str, str]]:
    recent = conversation.messages[-limit:] if conversation.messages else []
    return [{"role": message.role, "content": message.content} for message in recent]


# A question that refers to earlier turns cannot be embedded as-is — "does it
# mention that?" retrieves nothing. Anything else usually can be.
REFERENTIAL = re.compile(
    r"\b(it|that|this|those|these|they|them|there|the (one|same)|"
    r"above|previous|earlier|instead|also|too)\b",
    re.IGNORECASE,
)


def _needs_planning(question: str, history: list[dict[str, str]]) -> bool:
    """Whether the query planner earns its round-trip.

    Planning is a full LLM call before retrieval can even start, which is the
    largest single component of time-to-first-token. A short, self-contained
    opening question embeds perfectly well on its own, so the call is skipped
    for it and spent only where it changes the result.
    """
    words = question.split()
    if len(words) > 18:
        return True  # long questions often contain several separable asks
    if history:
        return True  # a follow-up may lean on earlier turns
    if REFERENTIAL.search(question):
        return True
    return False


async def _plan_queries(
    question: str, history: list[dict[str, str]], round_index: int
) -> list[str]:
    """Ask the fast model what to search for. Falls back to the raw question."""
    if round_index == 0 and not _needs_planning(question, history):
        return [question]

    instruction = QUERY_PLANNER.format(max_queries=settings.max_queries_per_round)
    if round_index > 0:
        instruction += (
            "\n\nThe previous search returned little that was relevant. Write DIFFERENT "
            "queries — use synonyms, the vocabulary a CV or statement would actually use, "
            "and broader phrasing."
        )

    messages = [{"role": "system", "content": instruction}]
    messages.extend(history[-4:])
    messages.append({"role": "user", "content": question})

    try:
        result = await llm.chat(
            messages, reasoning=False, temperature=0.1, max_tokens=300, json_mode=True
        )
        payload = extract_json(result.content)
        queries = [str(q).strip() for q in (payload.get("queries") or []) if str(q).strip()]
        return queries[: settings.max_queries_per_round]
    except Exception as exc:
        log.info("query_planning_fell_back", error=str(exc))
        return [question]


async def _search(
    user_key: str,
    queries: list[str],
    document_ids: list[uuid.UUID],
    user_token: str | None,
) -> list[dict]:
    """Run every query for a round concurrently.

    Each is an embedding call plus a vector scan, around a second apiece, and
    they do not depend on each other — running them in sequence put three
    seconds of avoidable latency in front of the first token.
    """

    async def one(query: str) -> list[dict]:
        response = await docs.post(
            "/internal/search",
            json={
                "user_key": user_key,
                "query": query,
                "top_k": settings.top_k,
                "document_ids": [str(d) for d in document_ids],
                "max_distance": settings.max_distance,
            },
            user_token=user_token,
        )
        return response.get("hits", [])

    results = await asyncio.gather(*(one(query) for query in queries), return_exceptions=True)

    seen: dict[str, dict] = {}
    for result in results:
        if isinstance(result, BaseException):
            log.warning("search_query_failed", error=str(result)[:200])
            continue
        for hit in result:
            # The same chunk found by two queries keeps its best distance.
            existing = seen.get(hit["chunk_id"])
            if existing is None or hit["distance"] < existing["distance"]:
                seen[hit["chunk_id"]] = hit
    return sorted(seen.values(), key=lambda hit: hit["distance"])


async def retrieve(
    *,
    user_key: str,
    question: str,
    conversation: Conversation,
    user_token: str | None,
) -> RetrievalOutcome:
    # The caller has already appended this turn's question to the conversation,
    # so the last message IS the question. Including it here made every
    # question look like a follow-up and forced a planning round-trip on all
    # of them.
    prior = [m for m in conversation.messages if m.content != question]
    history = [{"role": m.role, "content": m.content} for m in prior[-4:]]
    outcome = RetrievalOutcome()
    started = time.perf_counter()

    try:
        listing = await docs.get(
            "/internal/documents", params={"user_key": user_key}, user_token=user_token
        )
        indexed = [d for d in listing.get("items", []) if d["status"] == "indexed"]
        if not indexed:
            outcome.has_documents = False
            return outcome
    except UpstreamError:
        # Retrieval is the whole point; surface the failure rather than
        # answering ungrounded.
        raise

    for round_index in range(settings.max_search_rounds):
        queries = await _plan_queries(question, history, round_index)
        if not queries:
            break
        outcome.queries.extend(queries)
        outcome.rounds = round_index + 1

        hits = await _search(user_key, queries, list(conversation.document_ids or []), user_token)
        merged = {hit["chunk_id"]: hit for hit in outcome.hits}
        for hit in hits:
            existing = merged.get(hit["chunk_id"])
            if existing is None or hit["distance"] < existing["distance"]:
                merged[hit["chunk_id"]] = hit
        outcome.hits = sorted(merged.values(), key=lambda hit: hit["distance"])

        # A second, reworded round is a rescue for a search that found
        # nothing — not a refinement of one that found something. Relevant
        # matches routinely sit just outside any "strong" cutoff (the best hit
        # for a plain skills question measures 0.64), so gating on hit quality
        # made the rescue fire on nearly every question and doubled the wait
        # for no change in the answer.
        if outcome.hits:
            break

    outcome.hits = outcome.hits[: settings.top_k]
    log.info(
        "retrieval_complete",
        rounds=outcome.rounds,
        queries=len(outcome.queries),
        hits=len(outcome.hits),
        strong=outcome.strong_hits,
        ms=int((time.perf_counter() - started) * 1000),
    )
    return outcome


def _trim_to_budget(hits: list[dict], budget: int) -> list[dict]:
    kept: list[dict] = []
    used = 0
    for hit in hits:
        size = len(hit["content"])
        if used + size > budget and kept:
            break
        kept.append(hit)
        used += size
    return kept


def build_messages(
    *,
    question: str,
    conversation: Conversation,
    outcome: RetrievalOutcome,
    voice: bool,
    web: bool = False,
    opportunity: dict | None = None,
    use_documents: bool = True,
) -> tuple[list[dict[str, str]], list[dict], bool]:
    """Returns (messages, citable hits, grounded)."""
    history = _history(conversation, settings.history_turns)
    context_suffix = ""
    if opportunity:
        context_suffix += OPPORTUNITY_CONTEXT.format(
            opportunity=describe_opportunity(opportunity)
        )

    # Dossier off: answer generally, and say so rather than implying the
    # answer came from their documents.
    if not use_documents:
        system = (WEB_ONLY if web else GENERAL_ONLY) + context_suffix
        return (
            [
                {"role": "system", "content": system},
                *history,
                {"role": "user", "content": question},
            ],
            [],
            False,
        )

    # With the web on, thin retrieval is no longer a dead end — the assistant can
    # go and look instead of refusing.
    if web and (not outcome.has_documents or not outcome.is_sufficient):
        return (
            [
                {"role": "system", "content": WEB_ONLY + context_suffix},
                *history,
                {"role": "user", "content": question},
            ],
            [],
            False,
        )

    if not outcome.has_documents:
        return (
            [
                {"role": "system", "content": NO_DOCUMENTS + context_suffix},
                *history,
                {"role": "user", "content": question},
            ],
            [],
            False,
        )

    if not outcome.is_sufficient:
        return (
            [
                {"role": "system", "content": NO_CONTEXT + context_suffix},
                *history,
                {"role": "user", "content": f"Their question was: {question}"},
            ],
            [],
            False,
        )

    hits = _trim_to_budget(outcome.hits, settings.max_context_chars)
    system = GROUNDED_ANSWER.format(voice_hint=VOICE_HINT if voice else "")
    if web:
        system += WEB_ENABLED
    system += context_suffix

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": (
                f"EXCERPTS FROM YOUR DOCUMENTS\n\n{build_context_block(hits)}\n\n"
                f"---\nQUESTION: {question}"
            ),
        }
    )
    return messages, hits, True


async def answer(
    *,
    question: str,
    conversation: Conversation,
    outcome: RetrievalOutcome,
    reasoning: bool,
    voice: bool,
    web: bool = False,
    opportunity: dict | None = None,
    use_documents: bool = True,
) -> tuple[Message, list[dict], list]:
    started = time.perf_counter()
    messages, hits, grounded = build_messages(
        question=question,
        conversation=conversation,
        outcome=outcome,
        voice=voice,
        web=web,
        opportunity=opportunity,
        use_documents=use_documents,
    )

    result = await llm.chat(
        messages,
        reasoning=reasoning,
        temperature=0.2,
        max_tokens=1200 if voice else 2000,
        web_search=web,
    )

    message = Message(
        conversation_id=conversation.id,
        role=Role.ASSISTANT,
        content=result.content,
        used_reasoning=reasoning,
        reasoning=(result.reasoning or "")[:20000] or None,
        search_queries=outcome.queries,
        grounded=grounded,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
        used_web=web,
        meta={
            "retrieval_rounds": outcome.rounds,
            "hits_considered": len(outcome.hits),
            "strong_hits": outcome.strong_hits,
            "has_documents": outcome.has_documents,
            "web_results": len(result.web_citations),
            "cost": result.cost,
            "opportunity": (opportunity or {}).get("title"),
        },
    )
    return message, hits, result.web_citations


async def generate_title(question: str) -> str:
    try:
        result = await llm.chat(
            [{"role": "user", "content": TITLE_PROMPT.format(message=question[:500])}],
            reasoning=False,
            temperature=0.3,
            max_tokens=32,
        )
        title = result.content.strip().strip('"').strip()
        return title[:300] or question[:60]
    except Exception:
        return question[:60]


async def refine_email(
    *,
    subject: str,
    body: str,
    opportunity: dict | None,
    contact_name: str | None,
    applicant_context: str | None,
) -> dict:
    """Sharpen a drafted enquiry without inventing anything about the applicant.

    Grounded in their own documents where we have them: the model may tighten a
    claim the applicant already made, but never add a credential.
    """
    parts: list[str] = []
    if opportunity:
        parts.append(f"THE OPPORTUNITY\n{describe_opportunity(opportunity)}")
    if contact_name:
        parts.append(f"WRITING TO: {contact_name}")
    if applicant_context:
        parts.append(
            "WHAT THE APPLICANT'S OWN DOCUMENTS SAY (the only facts about them you "
            f"may rely on)\n{applicant_context}"
        )
    parts.append(f"CURRENT SUBJECT\n{subject}")
    parts.append(f"CURRENT DRAFT\n{body}")

    result = await llm.chat(
        [
            {"role": "system", "content": EMAIL_REFINE},
            {"role": "user", "content": "\n\n---\n\n".join(parts)},
        ],
        reasoning=False,
        temperature=0.4,
        max_tokens=1600,
        json_mode=True,
    )
    payload = extract_json(result.content)

    return {
        "subject": str(payload.get("subject") or subject)[:500],
        "body": str(payload.get("body") or body),
        "changes": [str(c)[:300] for c in (payload.get("changes") or [])][:6],
        "warnings": [str(w)[:300] for w in (payload.get("warnings") or [])][:6],
        "model": result.model,
    }
