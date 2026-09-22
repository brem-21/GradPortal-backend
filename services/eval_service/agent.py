"""The evaluation run: fetch documents, review each, then chair the committee."""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from eval_service.config import settings
from eval_service.models import (
    DocumentAssessment,
    EvaluationRun,
    Finding,
    RunStatus,
    Severity,
)
from eval_service.prompts import committee_synthesis_prompt, document_review_prompt
from eval_service.rubrics import Track, get_rubric
from shared.errors import UpstreamError, ValidationError
from shared.http import ServiceClient
from shared.llm import OpenRouterClient, extract_json

log = structlog.get_logger(__name__)

llm = OpenRouterClient(settings)
docs = ServiceClient(settings.doc_service_url, settings.internal_service_token, "doc-service")

# Documents a committee expects to see for each track.
EXPECTED_KINDS = {
    Track.MASTERS: ["cv", "sop", "motivation_letter", "recommendation", "transcript"],
    Track.PHD: ["cv", "sop", "recommendation", "research_proposal", "transcript"],
}

VERDICTS = {"competitive", "borderline", "needs work", "not ready"}


def _band_to_percent(score_0_5: float) -> float:
    return max(0.0, min(100.0, (score_0_5 / 5.0) * 100.0))


async def _fetch_documents(
    user_key: str, document_ids: list[uuid.UUID], user_token: str | None
) -> list[dict]:
    """Pull full text from doc-service.

    Whole documents, not retrieved chunks: assessing whether an SOP builds an
    argument requires the whole argument.
    """
    if document_ids:
        results = await asyncio.gather(
            *(
                docs.get(
                    f"/internal/documents/{document_id}/text",
                    params={"user_key": user_key},
                    user_token=user_token,
                )
                for document_id in document_ids
            ),
            return_exceptions=True,
        )
        documents = []
        for document_id, result in zip(document_ids, results, strict=True):
            if isinstance(result, Exception):
                log.warning("document_fetch_failed", document_id=str(document_id))
                continue
            documents.append(result)
        return documents

    listing = await docs.get(
        "/internal/documents", params={"user_key": user_key}, user_token=user_token
    )
    indexed = [item for item in listing.get("items", []) if item["status"] == "indexed"]
    fetched = await asyncio.gather(
        *(
            docs.get(
                f"/internal/documents/{item['id']}/text",
                params={"user_key": user_key},
                user_token=user_token,
            )
            for item in indexed[: settings.max_documents_per_run]
        ),
        return_exceptions=True,
    )
    return [item for item in fetched if not isinstance(item, Exception)]


async def _review_document(
    run: EvaluationRun, document: dict
) -> tuple[DocumentAssessment, int, int]:
    kind = document.get("kind", "other")
    title = document.get("title") or document.get("filename") or "Untitled"
    rubric = get_rubric(kind, run.track)

    text = (document.get("extracted_text") or "").strip()
    if len(text) > settings.max_chars_per_document:
        text = (
            text[: settings.max_chars_per_document]
            + "\n\n[Document truncated for review — the opening and body were assessed.]"
        )

    assessment = DocumentAssessment(
        document_id=uuid.UUID(str(document["id"])),
        document_kind=kind,
        document_title=title[:500],
        rubric_label=rubric.label,
        score=0.0,
        summary="",
    )

    if len(text) < 100:
        assessment.status = RunStatus.FAILED
        assessment.error = "Too little text to review."
        assessment.summary = "This document had almost no readable text, so it was not assessed."
        return assessment, 0, 0

    messages = document_review_prompt(
        rubric=rubric,
        track=run.track,
        document_kind=kind,
        document_title=title,
        document_text=text,
        target_field=run.target_field,
        target_programs=run.target_programs,
    )

    try:
        result = await llm.chat(
            messages,
            reasoning=settings.force_reasoning,
            temperature=0.2,
            max_tokens=4096,
            json_mode=True,
        )
        payload = extract_json(result.content)
    except Exception as exc:
        log.warning("document_review_failed", document_id=str(document["id"]), error=str(exc))
        assessment.status = RunStatus.FAILED
        assessment.error = str(exc)[:1000]
        assessment.summary = "This document could not be reviewed; see the error."
        return assessment, 0, 0

    assessment.reasoning = (result.reasoning or "")[:20000] or None
    assessment.summary = str(payload.get("summary", ""))[:4000]

    by_key = {criterion.key: criterion for criterion in rubric.criteria}
    raw_findings = payload.get("findings") or []
    seen: set[str] = set()
    weighted_total = 0.0
    weight_used = 0.0

    for position, raw in enumerate(raw_findings):
        key = str(raw.get("criterion_key", ""))
        criterion = by_key.get(key)
        if criterion is None or key in seen:
            continue
        seen.add(key)

        try:
            score = max(0.0, min(5.0, float(raw.get("score", 0))))
        except (TypeError, ValueError):
            score = 0.0

        severity = str(raw.get("severity", "")).lower()
        if severity not in Severity.ALL:
            # Infer from the score rather than dropping the finding.
            severity = (
                Severity.STRENGTH
                if score >= 4
                else Severity.MINOR
                if score >= 3
                else Severity.MAJOR
                if score >= 1.5
                else Severity.CRITICAL
            )

        assessment.findings.append(
            Finding(
                position=position,
                criterion_key=key,
                criterion_label=criterion.label,
                weight=criterion.weight,
                score=score,
                severity=severity,
                title=str(raw.get("title", criterion.label))[:300],
                detail=str(raw.get("detail", ""))[:4000],
                evidence=(str(raw["evidence"])[:2000] if raw.get("evidence") else None),
                suggestion=(str(raw["suggestion"])[:2000] if raw.get("suggestion") else None),
            )
        )
        weighted_total += score * criterion.weight
        weight_used += criterion.weight

    # Renormalise if the model skipped a criterion, so a missing answer does not
    # silently read as a zero.
    assessment.score = round(
        _band_to_percent(weighted_total / weight_used) if weight_used > 0 else 0.0, 1
    )
    assessment.status = RunStatus.COMPLETED
    return assessment, result.prompt_tokens, result.completion_tokens


async def _synthesise(run: EvaluationRun, assessments: list[DocumentAssessment]) -> tuple[int, int]:
    completed = [a for a in assessments if a.status == RunStatus.COMPLETED]
    if not completed:
        run.verdict = "not ready"
        run.summary = "No document could be assessed, so there is nothing to judge yet."
        return 0, 0

    present = sorted({a.document_kind for a in completed})
    missing = [kind for kind in EXPECTED_KINDS[run.track] if kind not in present]

    payload = [
        {
            "title": a.document_title,
            "kind": a.document_kind,
            "score": a.score,
            "summary": a.summary,
            "findings": [
                {
                    "criterion_label": f.criterion_label,
                    "score": f.score,
                    "severity": f.severity,
                    "title": f.title,
                }
                for f in a.findings
            ],
        }
        for a in completed
    ]

    messages = committee_synthesis_prompt(
        track=run.track,
        target_field=run.target_field,
        target_programs=run.target_programs,
        assessments=payload,
        present_kinds=present,
        missing_kinds=missing,
    )

    try:
        result = await llm.chat(
            messages,
            reasoning=settings.force_reasoning,
            temperature=0.25,
            max_tokens=2048,
            json_mode=True,
        )
        data = extract_json(result.content)
    except Exception as exc:
        log.warning("synthesis_failed", run_id=str(run.id), error=str(exc))
        # Per-document reviews are still worth showing; degrade rather than fail.
        run.verdict = None
        run.summary = (
            "Per-document reviews completed, but the cross-document summary could not "
            f"be generated: {exc}"
        )
        run.missing_documents = missing
        return 0, 0

    verdict = str(data.get("verdict", "")).strip().lower()
    run.verdict = verdict if verdict in VERDICTS else None
    run.summary = str(data.get("summary", ""))[:4000]
    run.committee_note = str(data.get("committee_note", ""))[:4000] or None
    run.priority_actions = [str(a)[:500] for a in (data.get("priority_actions") or [])][:5]
    run.missing_documents = [str(m)[:64] for m in (data.get("missing_documents") or missing)][:6]
    return result.prompt_tokens, result.completion_tokens


async def execute_run(
    db: Session, run: EvaluationRun, document_ids: list[uuid.UUID], user_token: str | None
) -> EvaluationRun:
    run.status = RunStatus.RUNNING
    run.model = llm.model_for(settings.force_reasoning)
    db.flush()

    try:
        documents = await _fetch_documents(run.user_key, document_ids, user_token)
    except UpstreamError as exc:
        run.status = RunStatus.FAILED
        run.error = str(exc)
        db.flush()
        return run

    if not documents:
        run.status = RunStatus.FAILED
        run.error = (
            "No indexed documents to evaluate. Upload a CV, statement of purpose or "
            "motivation letter first."
        )
        db.flush()
        return run

    documents = documents[: settings.max_documents_per_run]

    # Documents are independent, so review them concurrently — a five-document
    # file takes about as long as the slowest single review rather than the sum.
    reviewed = await asyncio.gather(*(_review_document(run, document) for document in documents))

    prompt_tokens = 0
    completion_tokens = 0
    assessments: list[DocumentAssessment] = []
    for assessment, used_prompt, used_completion in reviewed:
        assessment.run_id = run.id
        run.assessments.append(assessment)
        assessments.append(assessment)
        prompt_tokens += used_prompt
        completion_tokens += used_completion

    db.flush()

    synth_prompt, synth_completion = await _synthesise(run, assessments)
    prompt_tokens += synth_prompt
    completion_tokens += synth_completion

    scored = [a for a in assessments if a.status == RunStatus.COMPLETED]
    run.overall_score = round(sum(a.score for a in scored) / len(scored), 1) if scored else None
    run.prompt_tokens = prompt_tokens
    run.completion_tokens = completion_tokens
    run.status = RunStatus.COMPLETED if scored else RunStatus.FAILED
    if not scored:
        run.error = "Every document failed review."
    run.completed_at = datetime.now(UTC)
    db.flush()

    log.info(
        "evaluation_complete",
        run_id=str(run.id),
        track=run.track,
        documents=len(assessments),
        scored=len(scored),
        overall=run.overall_score,
        verdict=run.verdict,
    )
    return run


def validate_track(track: str) -> str:
    if track not in Track.ALL:
        raise ValidationError(f"track must be one of: {', '.join(Track.ALL)}")
    return track
