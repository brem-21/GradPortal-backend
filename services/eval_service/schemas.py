import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from eval_service.rubrics import Track


class StartEvaluation(BaseModel):
    track: str = Field(description="masters or phd")
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    # Empty means "everything I have uploaded".
    target_field: str | None = None
    target_programs: str | None = Field(
        default=None,
        description="Free text: the programmes or universities being applied to, "
        "used to judge programme-specific fit.",
    )

    def normalised_track(self) -> str:
        return self.track if self.track in Track.ALL else Track.MASTERS


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    criterion_key: str
    criterion_label: str
    weight: float
    score: float
    severity: str
    title: str
    detail: str
    evidence: str | None
    suggestion: str | None


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    document_kind: str
    document_title: str
    rubric_label: str
    score: float
    summary: str
    status: str
    error: str | None
    findings: list[FindingRead] = Field(default_factory=list)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track: str
    target_field: str | None
    target_programs: str | None
    status: str
    error: str | None
    overall_score: float | None
    verdict: str | None
    summary: str | None
    committee_note: str | None
    priority_actions: list[str]
    missing_documents: list[str]
    model: str | None
    created_at: datetime
    completed_at: datetime | None


class RunDetail(RunRead):
    assessments: list[AssessmentRead] = Field(default_factory=list)


class RunList(BaseModel):
    items: list[RunRead]
    total: int


class RubricCriterionRead(BaseModel):
    key: str
    label: str
    weight: float
    question: str
    strong_signal: str
    weak_signal: str


class RubricRead(BaseModel):
    document_kind: str
    track: str
    label: str
    reader: str
    criteria: list[RubricCriterionRead]
