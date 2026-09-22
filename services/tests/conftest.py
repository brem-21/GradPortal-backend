import io

import pytest
from docx import Document as DocxDocument


@pytest.fixture
def sample_cv_text() -> str:
    return """JANE OKONKWO
Accra, Ghana | jane.okonkwo@example.com | github.com/janeok

EDUCATION
BSc Computer Science, Kwame Nkrumah University of Science and Technology, 2021-2025
First Class Honours, CGPA 3.81/4.0
Relevant coursework: Machine Learning, Distributed Systems, Linear Algebra, Probability

EXPERIENCE
Data Engineering Intern, AmaliTech, Jun 2024 - Sep 2024
Built an Airflow pipeline ingesting 2.3M records daily from twelve partner APIs.
Cut nightly batch runtime from 4.1 hours to 38 minutes by repartitioning the Spark job.
Wrote the dbt models now used by the analytics team for weekly reporting.

Research Assistant, KNUST Vision Lab, Jan 2024 - Present
Trained a segmentation model on 8,400 annotated maize-leaf images, reaching 0.91 mIoU.
Co-authored a paper submitted to ICLR 2026 workshop track.

PUBLICATIONS
Okonkwo, J., Mensah, K. (2025). Lightweight segmentation for smallholder crop disease.
Under review, ICLR 2026 Workshop on Machine Learning for the Developing World.

SKILLS
Python, PyTorch, Spark, Airflow, dbt, PostgreSQL, Docker, Kubernetes
"""


@pytest.fixture
def sample_docx_bytes(sample_cv_text: str) -> bytes:
    document = DocxDocument()
    for line in sample_cv_text.split("\n"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
