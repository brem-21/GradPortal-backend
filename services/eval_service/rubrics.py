"""What an admissions committee actually looks for.

The criteria and their weights are the product here — they encode the difference
between how a master's file and a doctoral file get read. A master's committee is
asking "can this person succeed in our coursework and get hired after"; a PhD
committee is asking "can this person produce original research for five years,
and does someone here want to supervise it".

Weights within a document kind sum to 1.0.
"""

from dataclasses import dataclass, field


class Track:
    MASTERS = "masters"
    PHD = "phd"
    ALL = (MASTERS, PHD)


TRACK_LABELS = {Track.MASTERS: "Master's", Track.PHD: "PhD"}


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    weight: float
    # What the committee is actually asking. Goes verbatim into the prompt.
    question: str
    # What separates a 5 from a 2 on this criterion.
    strong_signal: str
    weak_signal: str


@dataclass(frozen=True)
class Rubric:
    document_kind: str
    track: str
    label: str
    reader: str
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def total_weight(self) -> float:
        return round(sum(c.weight for c in self.criteria), 4)


# --------------------------------------------------------------------------- CV

CV_MASTERS = Rubric(
    document_kind="cv",
    track=Track.MASTERS,
    label="CV — master's admission",
    reader="a graduate admissions reader screening for coursework readiness and employability",
    criteria=[
        Criterion(
            "technical_depth",
            "Technical depth and coursework",
            0.28,
            "Does the candidate demonstrably have the prerequisites for our core courses — programming, mathematics, statistics, systems?",
            "Named languages, frameworks and relevant advanced coursework with grades or projects that prove them.",
            "A list of buzzwords with no artefact, grade or project behind any of them.",
        ),
        Criterion(
            "impact_evidence",
            "Quantified impact",
            0.22,
            "Are accomplishments stated as outcomes with numbers, or as job descriptions?",
            "Each bullet carries a measurable result: scale, latency, accuracy, users, revenue, time saved.",
            "Bullets that begin 'Responsible for' and never state what changed.",
        ),
        Criterion(
            "relevant_experience",
            "Relevant experience",
            0.20,
            "Do internships, jobs or projects map onto the field the candidate is applying into?",
            "A coherent line of work in or adjacent to the target field, with increasing responsibility.",
            "Unrelated roles with no bridge drawn to the target field.",
        ),
        Criterion(
            "research_exposure",
            "Research and publication exposure",
            0.12,
            "Optional for a master's, but it distinguishes a funded applicant from an unfunded one.",
            "A thesis, a publication, a preprint, or sustained work in a lab.",
            "No independent or supervised research of any kind.",
        ),
        Criterion(
            "presentation",
            "Structure, length and readability",
            0.18,
            "Can a reader with ninety seconds find the qualification? Is it one to two pages, reverse-chronological, consistently formatted?",
            "Scannable, consistent, appropriately short, no typos, most relevant material first.",
            "Dense blocks, inconsistent dates, four pages, or a skills bar chart with no substance behind it.",
        ),
    ],
)

CV_PHD = Rubric(
    document_kind="cv",
    track=Track.PHD,
    label="CV — doctoral admission",
    reader="a faculty member deciding whether this person could produce original research in their lab",
    criteria=[
        Criterion(
            "research_output",
            "Research output and trajectory",
            0.34,
            "Is there evidence of producing research, not just consuming it? Publications, preprints, theses, conference work, open-source of research quality?",
            "Peer-reviewed or archived output with a clear statement of the candidate's own contribution.",
            "No output, or output where the candidate's role is indistinguishable from the supervisor's.",
        ),
        Criterion(
            "methodological_depth",
            "Methodological and technical depth",
            0.24,
            "Can this person run experiments independently — design, implement, analyse, and be honest about limitations?",
            "Specific methods, tooling and analysis named, with evidence of having applied them end to end.",
            "Method names appear but nothing shows they were used beyond a course assignment.",
        ),
        Criterion(
            "research_fit",
            "Fit to a research area",
            0.18,
            "Does the work cluster around a recognisable area a supervisor here would claim?",
            "A consistent thread across projects that maps to a named subfield.",
            "Scattered unrelated projects with no through-line.",
        ),
        Criterion(
            "academic_signals",
            "Academic signals",
            0.12,
            "Awards, competitive funding, teaching, reviewing, invited talks, strong grades in theory-heavy courses.",
            "Competitive selection of any kind, or evidence of being trusted with teaching or review.",
            "No external validation beyond course completion.",
        ),
        Criterion(
            "presentation",
            "Academic CV conventions",
            0.12,
            "Does it follow academic conventions — publications sectioned and properly cited, no corporate resume padding?",
            "Publications formatted as citations, clear sections, length appropriate to an academic CV.",
            "A business resume with a skills-percentage graphic submitted to a research programme.",
        ),
    ],
)

# -------------------------------------------------------------- Statement of purpose

SOP_MASTERS = Rubric(
    document_kind="sop",
    track=Track.MASTERS,
    label="Statement of purpose — master's",
    reader="an admissions committee member reading their fortieth statement that evening",
    criteria=[
        Criterion(
            "goal_clarity",
            "Clarity of goal",
            0.24,
            "By the end of the first paragraph, do I know what this person wants to do and why this degree is the route?",
            "A specific, plausible goal stated early, with the degree positioned as the necessary step.",
            "A general enthusiasm for the field with no stated destination.",
        ),
        Criterion(
            "program_fit",
            "Programme-specific fit",
            0.24,
            "Could this statement be sent to twenty other universities with the name swapped? If so it fails.",
            "Named courses, tracks, labs, faculty or facilities, with a reason each one matters to this candidate.",
            "Generic praise for the university's reputation, ranking or 'world-class faculty'.",
        ),
        Criterion(
            "preparation_evidence",
            "Evidence of preparation",
            0.22,
            "Are claims about ability backed by something that happened, or are they assertions?",
            "Concrete episodes — a project, a failure and what was learned, a specific technical obstacle overcome.",
            "Adjectives about oneself: passionate, hardworking, quick learner.",
        ),
        Criterion(
            "narrative_coherence",
            "Narrative coherence",
            0.16,
            "Do the paragraphs build an argument, or is it a chronology?",
            "Each paragraph advances the case; the ending connects back to the opening claim.",
            "A restatement of the CV in prose, in date order.",
        ),
        Criterion(
            "writing_quality",
            "Writing quality",
            0.14,
            "Is the prose clean enough that it never distracts from the content?",
            "Direct sentences, no clichés, correct grammar, within the stated word limit.",
            "Opening with a dictionary definition or a childhood anecdote; grammatical errors; over length.",
        ),
    ],
)

SOP_PHD = Rubric(
    document_kind="sop",
    track=Track.PHD,
    label="Statement of purpose — PhD",
    reader="a potential supervisor deciding whether to spend five years and their grant money on this person",
    criteria=[
        Criterion(
            "research_question",
            "Research question maturity",
            0.28,
            "Is there a real question here — something answerable, unresolved, and worth five years?",
            "A specific open problem, framed with awareness of why it is still open.",
            "A topic area named as though it were a question: 'I want to research AI in healthcare'.",
        ),
        Criterion(
            "literature_positioning",
            "Positioning in the literature",
            0.20,
            "Does the candidate know what has already been tried, and can they say where their idea sits relative to it?",
            "Specific prior work cited and engaged with, including its limitations.",
            "No engagement with existing work, or name-dropping papers without discussing them.",
        ),
        Criterion(
            "supervisor_fit",
            "Supervisor and group fit",
            0.22,
            "Has this person identified who would supervise them and why that specific person? Have they read that person's work?",
            "Named faculty with a substantive reason — a specific paper, method or dataset that connects to the candidate's plan.",
            "No named supervisor, or three named with no reason, or a name whose research area is misdescribed.",
        ),
        Criterion(
            "research_preparation",
            "Demonstrated research capability",
            0.20,
            "Has this person already done research, and can they describe their own contribution precisely?",
            "A described project with the candidate's specific role, the methods, the result, and what went wrong.",
            "Coursework and enthusiasm presented as research experience.",
        ),
        Criterion(
            "writing_quality",
            "Academic writing quality",
            0.10,
            "Does this read like someone who could write a thesis chapter?",
            "Precise, structured, appropriately technical, hedged where the evidence is thin.",
            "Overclaiming, vagueness, or prose that cannot sustain a technical argument.",
        ),
    ],
)

# ------------------------------------------------------------- Motivation letter

MOTIVATION_BASE = [
    Criterion(
        "motivation_authenticity",
        "Authenticity of motivation",
        0.28,
        "Does the reason for applying feel specific to this person, or assembled from a template?",
        "A concrete origin for the interest, tied to something the candidate actually did.",
        "Sweeping statements about passion, or a childhood story with no link to the present.",
    ),
    Criterion(
        "program_fit",
        "Fit to this programme",
        0.28,
        "Does the letter show the candidate understands what this programme specifically offers?",
        "Named programme elements and a reason each matters to this candidate's plan.",
        "Interchangeable praise that would suit any institution.",
    ),
    Criterion(
        "contribution",
        "What the candidate brings",
        0.22,
        "What would this person add to the cohort that the next applicant would not?",
        "A specific perspective, skill or experience, with evidence, framed as useful to others.",
        "Only what the candidate wants to receive, never what they would contribute.",
    ),
    Criterion(
        "structure_concision",
        "Structure and concision",
        0.22,
        "Is it one page, purposeful, and free of filler?",
        "Tight paragraphs, one idea each, within length, ending on the ask.",
        "Repetition of the CV, excessive length, or no clear closing.",
    ),
]

# --------------------------------------------------------------- Recommendation

RECOMMENDATION_BASE = [
    Criterion(
        "recommender_credibility",
        "Recommender credibility and relationship",
        0.24,
        "Who is writing, how well do they actually know the candidate, and in what capacity?",
        "A named role, stated duration and context of the relationship, and direct supervision of relevant work.",
        "A letter from someone who taught one large lecture course and can only confirm a grade.",
    ),
    Criterion(
        "evidence_specificity",
        "Specificity of evidence",
        0.28,
        "Does the letter describe particular things the candidate did, or list adjectives?",
        "Named projects, specific incidents, the candidate's exact contribution, quoted results.",
        "'Diligent, intelligent and a pleasure to teach' with nothing behind it.",
    ),
    Criterion(
        "comparative_signal",
        "Comparative ranking",
        0.22,
        "Does the writer place the candidate against a peer group they are qualified to compare within?",
        "An explicit comparison with a stated reference group and cohort size.",
        "No comparison at all, or a vague 'one of the best' with no denominator.",
    ),
    Criterion(
        "competency_coverage",
        "Coverage of what the committee needs",
        0.16,
        "Does it speak to the competencies this programme actually screens for?",
        "Addresses independence, technical ability, resilience and communication — with evidence.",
        "Only personality traits, or only classroom performance for a research degree.",
    ),
    Criterion(
        "red_flags",
        "Absence of damaging signals",
        0.10,
        "Is there faint praise, hedging, or a conspicuous omission a committee would notice?",
        "Consistently positive with no qualifications the reader has to interpret.",
        "'Completed the work as required', unexplained gaps in the endorsement, or lukewarm closing.",
    ),
]

# ------------------------------------------------------------ Research proposal

PROPOSAL_PHD = Rubric(
    document_kind="research_proposal",
    track=Track.PHD,
    label="Research proposal — PhD",
    reader="a committee assessing whether this is a viable doctoral project",
    criteria=[
        Criterion(
            "significance",
            "Significance of the problem",
            0.22,
            "If this succeeded, would anyone in the field care, and can the candidate say who?",
            "A clear statement of what changes if the question is answered, and for whom.",
            "Importance asserted rather than argued.",
        ),
        Criterion(
            "novelty",
            "Novelty and positioning",
            0.22,
            "Is this actually new, and does the candidate know the work it builds on?",
            "Prior approaches named, their limitations stated, and the gap identified precisely.",
            "A proposal for something already solved, or no engagement with prior work.",
        ),
        Criterion(
            "methodology",
            "Methodological soundness",
            0.24,
            "Is there a plausible method, with data, evaluation and a way of being wrong?",
            "Specific methods, data sources, baselines, evaluation metrics and stated risks.",
            "'I will use machine learning to' with no design, data or evaluation named.",
        ),
        Criterion(
            "feasibility",
            "Feasibility and scope",
            0.20,
            "Can this be done in three to five years by one person with the resources available here?",
            "Phased plan with milestones, scope honestly bounded, dependencies acknowledged.",
            "A proposal that would take a whole lab a decade, or one thin enough for a master's thesis.",
        ),
        Criterion(
            "alignment",
            "Alignment with the host group",
            0.12,
            "Does this need what this specific department has — equipment, data, expertise?",
            "An explicit connection to the group's capability or ongoing work.",
            "A proposal with no reason to be at this institution.",
        ),
    ],
)

# ------------------------------------------------------------------- Transcript

TRANSCRIPT_BASE = [
    Criterion(
        "prerequisite_coverage",
        "Prerequisite coverage",
        0.40,
        "Are the courses this programme requires actually present and passed?",
        "Core prerequisites present with solid grades.",
        "Missing prerequisites, or passes in the lowest band in the courses that matter most.",
    ),
    Criterion(
        "trajectory",
        "Grade trajectory",
        0.30,
        "Is performance improving, flat or declining — and is the most recent year strong?",
        "Upward trend, strongest results in the final and most advanced courses.",
        "Decline in the final year, or strong grades only in unrelated subjects.",
    ),
    Criterion(
        "rigour",
        "Rigour of the courses taken",
        0.30,
        "Did the candidate take the demanding options or avoid them?",
        "Advanced theory and project courses chosen voluntarily.",
        "A pattern of choosing the lightest available options.",
    ),
]


def _rubric(kind: str, track: str, label: str, reader: str, criteria: list[Criterion]) -> Rubric:
    return Rubric(document_kind=kind, track=track, label=label, reader=reader, criteria=criteria)


RUBRICS: dict[tuple[str, str], Rubric] = {}

for _rub in (CV_MASTERS, CV_PHD, SOP_MASTERS, SOP_PHD, PROPOSAL_PHD):
    RUBRICS[(_rub.document_kind, _rub.track)] = _rub

for _track in Track.ALL:
    _track_label = TRACK_LABELS[_track]
    RUBRICS[("motivation_letter", _track)] = _rubric(
        "motivation_letter",
        _track,
        f"Motivation letter — {_track_label}",
        f"an admissions reader for a {_track_label} programme",
        MOTIVATION_BASE,
    )
    RUBRICS[("recommendation", _track)] = _rubric(
        "recommendation",
        _track,
        f"Recommendation letter — {_track_label}",
        f"a committee member weighing third-party evidence for a {_track_label} applicant",
        RECOMMENDATION_BASE,
    )
    RUBRICS[("transcript", _track)] = _rubric(
        "transcript",
        _track,
        f"Transcript — {_track_label}",
        f"a reader checking academic eligibility for a {_track_label} programme",
        TRANSCRIPT_BASE,
    )

# A research proposal submitted for a master's is read against the PhD rubric with
# feasibility expectations relaxed in the prompt, rather than left unscored.
RUBRICS[("research_proposal", Track.MASTERS)] = _rubric(
    "research_proposal",
    Track.MASTERS,
    "Research proposal — master's",
    "a reader assessing a dissertation proposal for a taught or research master's",
    PROPOSAL_PHD.criteria,
)

# Anything uncategorised still gets read, against generic application criteria.
GENERIC = [
    Criterion(
        "relevance",
        "Relevance to the application",
        0.34,
        "Does this document help the committee decide, or is it filler?",
        "Adds evidence the other documents do not carry.",
        "Duplicates the CV or is unrelated to the application.",
    ),
    Criterion(
        "evidence_quality",
        "Quality of evidence",
        0.34,
        "Are claims supported by specifics?",
        "Concrete, verifiable detail.",
        "Assertion without support.",
    ),
    Criterion(
        "presentation",
        "Presentation",
        0.32,
        "Is it well organised and free of errors?",
        "Clear structure, correct language, appropriate length.",
        "Disorganised or error-ridden.",
    ),
]
for _track in Track.ALL:
    RUBRICS[("other", _track)] = _rubric(
        "other",
        _track,
        f"General document — {TRACK_LABELS[_track]}",
        "an admissions reader",
        GENERIC,
    )


def get_rubric(document_kind: str, track: str) -> Rubric:
    return RUBRICS.get((document_kind, track)) or RUBRICS[("other", track)]


def supported_kinds(track: str) -> list[str]:
    return sorted({kind for kind, rubric_track in RUBRICS if rubric_track == track})
