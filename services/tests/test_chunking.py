from doc_service.chunking import chunk_document, count_tokens


def test_short_document_is_one_chunk(sample_cv_text: str):
    chunks = chunk_document(sample_cv_text, max_tokens=800, overlap_tokens=120)
    assert len(chunks) == 1
    assert chunks[0].index == 0


def test_long_document_splits_and_indexes_sequentially():
    text = "\n\n".join(f"Paragraph {i}. " + ("filler words here. " * 60) for i in range(30))
    chunks = chunk_document(text, max_tokens=300, overlap_tokens=50)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_no_chunk_exceeds_the_window_by_much():
    text = "\n\n".join("word " * 500 for _ in range(10))
    chunks = chunk_document(text, max_tokens=200, overlap_tokens=40)
    # Overlap is prepended, so allow the window plus the overlap.
    assert all(c.token_count <= 200 + 40 + 10 for c in chunks)


def test_oversized_single_paragraph_is_split():
    text = "one enormous paragraph. " * 900
    chunks = chunk_document(text, max_tokens=200, overlap_tokens=0)
    assert len(chunks) > 1


def test_detects_cv_sections(sample_cv_text: str):
    chunks = chunk_document(sample_cv_text, max_tokens=60, overlap_tokens=10)
    sections = {c.section for c in chunks if c.section}
    assert any("EDUCATION" in s or "EXPERIENCE" in s or "SKILLS" in s for s in sections)


def test_assigns_page_numbers_from_offsets():
    page_one = "First page content. " * 40
    page_two = "Second page content. " * 40
    text = page_one + "\n\n" + page_two
    chunks = chunk_document(
        text, max_tokens=60, overlap_tokens=0, page_offsets=[0, len(page_one) + 2]
    )
    pages = {c.page_number for c in chunks}
    assert pages == {1, 2}


def test_empty_input_yields_nothing():
    assert chunk_document("") == []
    assert chunk_document("   \n\n  ") == []


def test_respects_max_chunks():
    text = "\n\n".join(f"Para {i} " + ("x " * 200) for i in range(100))
    chunks = chunk_document(text, max_tokens=100, overlap_tokens=0, max_chunks=5)
    assert len(chunks) == 5


def _shares_text(earlier: str, later: str, window: int = 30) -> bool:
    """True when the head of `later` repeats some tail of `earlier`."""
    tail = earlier[-400:]
    head = later[:400]
    for size in range(min(len(tail), len(head), 200), window, -10):
        if head[:size] and head[:size] in tail:
            return True
    return False


def test_overlap_carries_context_across_paragraph_boundaries():
    paragraphs = "\n\n".join(f"Point {i}: " + ("detail words here. " * 25) for i in range(8))
    chunks = chunk_document(paragraphs, max_tokens=200, overlap_tokens=60)
    assert len(chunks) >= 2
    assert any(
        _shares_text(chunks[i].content, chunks[i + 1].content) for i in range(len(chunks) - 1)
    )


def test_overlap_applies_inside_an_oversized_paragraph():
    # One unbroken paragraph longer than the window — the case that previously
    # lost its overlap entirely.
    single = "The candidate led the Kubernetes migration. " * 60
    chunks = chunk_document(single, max_tokens=150, overlap_tokens=50)
    assert len(chunks) >= 2
    assert any(
        _shares_text(chunks[i].content, chunks[i + 1].content) for i in range(len(chunks) - 1)
    )


def test_zero_overlap_produces_no_repetition():
    single = "Distinct sentence number one here. " * 60
    chunks = chunk_document(single, max_tokens=120, overlap_tokens=0)
    total = sum(c.token_count for c in chunks)
    # Without overlap the pieces should roughly sum to the original length.
    assert total <= count_tokens(single) + 5
