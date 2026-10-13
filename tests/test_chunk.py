from isss_bot.chunk import MAX_TOKENS, chunk_page, estimate_tokens, split_sections

PAGE = """# Curricular Practical Training (CPT)

CPT is an F-1 off-campus work authorization for training that is part of the curriculum.

## Eligibility Requirements

- Enrolled full-time for one academic year.
- Have a job offer related to your field.

## Procedure

### Co-op students

Meet your co-op advisor first.

### Other students

Meet your academic advisor first.
"""


def test_split_sections_tracks_heading_paths():
    sections = split_sections(PAGE)
    assert [section.path for section in sections] == [
        [],
        ["Eligibility Requirements"],
        ["Procedure"],
        ["Procedure", "Co-op students"],
        ["Procedure", "Other students"],
    ]
    assert sections[1].paragraphs == [
        "- Enrolled full-time for one academic year.\n- Have a job offer related to your field."
    ]


def test_small_sections_are_merged_and_prefixed_with_their_path():
    chunks = chunk_page("Curricular Practical Training (CPT)", PAGE)
    assert len(chunks) == 1
    assert chunks[0].heading_path == "Curricular Practical Training (CPT)"
    assert "## Eligibility Requirements" in chunks[0].content
    assert "### Co-op students\n\nMeet your co-op advisor first." in chunks[0].content


def test_sections_under_one_heading_share_its_path():
    filler = "Details about the procedure. " * 20
    text = f"# CPT\n\n{filler}\n\n## Eligibility\n\n{filler}\n\n## Procedure\n\n### Co-op\n\n{filler}\n\n### Others\n\n{filler}"
    paths = [chunk.heading_path for chunk in chunk_page("CPT", text)]
    assert paths == ["CPT", "CPT › Eligibility", "CPT › Procedure"]


def test_long_sections_are_split_without_losing_text():
    paragraphs = [f"Sentence number {n} about OPT rules and deadlines." for n in range(400)]
    text = "# OPT\n\n## Rules\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_page("OPT", text)
    assert len(chunks) > 1
    assert all(chunk.token_count <= MAX_TOKENS for chunk in chunks)
    assert all(chunk.heading_path == "OPT › Rules" for chunk in chunks)
    joined = "\n\n".join(chunk.content for chunk in chunks)
    assert all(paragraph in joined for paragraph in paragraphs)


def test_a_single_huge_paragraph_is_split_by_sentences():
    text = "# Guide\n\n" + " ".join(f"Step {n} explains what to bring." for n in range(600))
    chunks = chunk_page("Guide", text)
    assert len(chunks) > 1
    assert all(chunk.token_count <= MAX_TOKENS for chunk in chunks)


def test_headings_stay_with_their_text():
    filler = "Text. " * 300
    text = f"# FAQ\n\n## Questions\n\n### First question?\n\n{filler}\n\n### Second question?\n\nShort answer."
    for chunk in chunk_page("FAQ", text):
        assert not chunk.content.rstrip().endswith("?")


def test_pages_without_real_content_produce_no_chunks():
    assert chunk_page("ISSS Events", "# ISSS Events") == []
    assert chunk_page("Event information not found", "# Event information not found\n\nLoading...") == []


def test_estimate_tokens():
    assert estimate_tokens("abcd" * 100) == 100
