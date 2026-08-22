from app.ingestion.pipeline import chunk_text


def test_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_paragraph_grouping_under_size():
    text = "\n\n".join(f"para {i} " + "x" * 50 for i in range(5))
    chunks = chunk_text(text, size=200, overlap=20)
    assert all(len(c) <= 200 for c in chunks)
    assert len(chunks) >= 2


def test_oversized_paragraph_slides_window():
    huge = "y" * 2500
    chunks = chunk_text(huge, size=500, overlap=100)
    assert len(chunks) >= 4
    assert all(len(c) <= 500 for c in chunks)


def test_tiny_trailing_chunk_merged():
    text = "a" * 300 + "\n\n" + "b" * 300 + "\n\ntiny"
    chunks = chunk_text(text, size=400)
    assert "tiny" in chunks[-1]
