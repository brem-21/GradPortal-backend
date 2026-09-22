import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from eval_service import agent
from eval_service.config import settings
from eval_service.db import get_db
from eval_service.models import DocumentAssessment, EvaluationRun, RunStatus
from eval_service.rubrics import RUBRICS, Track, get_rubric
from eval_service.schemas import (
    RubricCriterionRead,
    RubricRead,
    RunDetail,
    RunList,
    RunRead,
    StartEvaluation,
)
from shared.auth import Principal, build_auth_dependency
from shared.errors import NotFoundError

principal_dep = build_auth_dependency(settings)
router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    return header.removeprefix("Bearer ").strip() or None


def _load(db: Session, run_id: uuid.UUID, user_key: str) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun)
        .options(selectinload(EvaluationRun.assessments).selectinload(DocumentAssessment.findings))
        .where(EvaluationRun.id == run_id, EvaluationRun.user_key == user_key)
    )
    if run is None:
        raise NotFoundError("Evaluation not found")
    return run


@router.get("/rubrics", response_model=list[RubricRead])
def list_rubrics(track: str | None = None) -> list[RubricRead]:
    """The criteria the reviewer scores against.

    Exposed so the UI can show an applicant what is being judged before they
    spend a run — an evaluation they cannot interpret is not worth much.
    """
    wanted = [track] if track in Track.ALL else list(Track.ALL)
    return [
        RubricRead(
            document_kind=rubric.document_kind,
            track=rubric.track,
            label=rubric.label,
            reader=rubric.reader,
            criteria=[
                RubricCriterionRead(
                    key=c.key,
                    label=c.label,
                    weight=c.weight,
                    question=c.question,
                    strong_signal=c.strong_signal,
                    weak_signal=c.weak_signal,
                )
                for c in rubric.criteria
            ],
        )
        for (_, rubric_track), rubric in sorted(RUBRICS.items())
        if rubric_track in wanted
    ]


@router.get("/rubrics/{document_kind}", response_model=RubricRead)
def read_rubric(document_kind: str, track: str = Track.MASTERS) -> RubricRead:
    rubric = get_rubric(document_kind, track if track in Track.ALL else Track.MASTERS)
    return RubricRead(
        document_kind=rubric.document_kind,
        track=rubric.track,
        label=rubric.label,
        reader=rubric.reader,
        criteria=[
            RubricCriterionRead(
                key=c.key,
                label=c.label,
                weight=c.weight,
                question=c.question,
                strong_signal=c.strong_signal,
                weak_signal=c.weak_signal,
            )
            for c in rubric.criteria
        ],
    )


@router.post("", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
async def start_evaluation(
    payload: StartEvaluation,
    request: Request,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> RunDetail:
    """Run a full committee review.

    Synchronous: a five-document review takes 30-90 seconds on a reasoning
    model, and an applicant watching a spinner is better served by a result than
    by a job id they have to poll.
    """
    track = agent.validate_track(payload.normalised_track())

    run = EvaluationRun(
        user_key=principal.user_key,
        track=track,
        target_field=payload.target_field,
        target_programs=payload.target_programs,
        status=RunStatus.QUEUED,
    )
    db.add(run)
    db.flush()

    await agent.execute_run(db, run, payload.document_ids, _bearer(request))
    db.flush()
    db.refresh(run)
    return RunDetail.model_validate(run)


@router.get("", response_model=RunList)
def list_runs(
    track: str | None = None,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> RunList:
    statement = (
        select(EvaluationRun)
        .where(EvaluationRun.user_key == principal.user_key)
        .order_by(EvaluationRun.created_at.desc())
    )
    if track in Track.ALL:
        statement = statement.where(EvaluationRun.track == track)
    rows = list(db.scalars(statement).all())
    total = (
        db.scalar(
            select(func.count())
            .select_from(EvaluationRun)
            .where(EvaluationRun.user_key == principal.user_key)
        )
        or 0
    )
    return RunList(items=[RunRead.model_validate(row) for row in rows], total=total)


@router.get("/{run_id}", response_model=RunDetail)
def read_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> RunDetail:
    return RunDetail.model_validate(_load(db, run_id, principal.user_key))


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(principal_dep),
    db: Session = Depends(get_db),
) -> None:
    db.delete(_load(db, run_id, principal.user_key))
