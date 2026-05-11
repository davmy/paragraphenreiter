import asyncio
import json
from unittest.mock import MagicMock, patch

from rag import ParagraphenreiterRAG

SAMPLE_INDEX = [
    {
        "abbreviation": "BGB",
        "title": "Bürgerliches Gesetzbuch",
        "url": "https://www.gesetze-im-internet.de/bgb/",
        "path": "/bgb/",
    },
]


def make_rag() -> ParagraphenreiterRAG:
    rag = ParagraphenreiterRAG()
    rag.law_index = SAMPLE_INDEX
    return rag


def make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    return block


# ── _identify_relevant_laws ──────────────────────────────


def test_identify_relevant_laws_empty_candidates():
    assert make_rag()._identify_relevant_laws("Frage", []) == []


def test_identify_relevant_laws_parses_json_response():
    rag = make_rag()
    rag.client.messages.create.return_value.content = [make_text_block('["BGB"]')]
    result = rag._identify_relevant_laws("Kaufvertrag", SAMPLE_INDEX)
    assert result == ["BGB"]


def test_identify_relevant_laws_falls_back_on_no_json():
    rag = make_rag()
    rag.client.messages.create.return_value.content = [make_text_block("keine Liste")]
    result = rag._identify_relevant_laws("Frage", SAMPLE_INDEX)
    assert result == []


def test_identify_relevant_laws_falls_back_on_invalid_json():
    rag = make_rag()
    rag.client.messages.create.return_value.content = [
        make_text_block("[not valid json}")
    ]
    result = rag._identify_relevant_laws("Frage", SAMPLE_INDEX)
    assert result == []


# ── stream_answer ────────────────────────────────────────


def _make_mock_stream(tokens: list[str]) -> MagicMock:
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.text_stream = iter(tokens)
    return mock


async def _collect(gen) -> list[dict]:
    events = []
    async for chunk in gen:
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    return events


def test_stream_answer_yields_content_and_done():
    rag = make_rag()

    fake_law = {
        "abbreviation": "BGB",
        "title": "Bürgerliches Gesetzbuch",
        "url": "https://www.gesetze-im-internet.de/bgb/",
        "sections": [
            {
                "text": "§ 433",
                "url": "https://www.gesetze-im-internet.de/bgb/__433.html",
            }
        ],
        "content": "Kaufvertrag Inhalt",
    }

    with (
        patch.object(rag, "_identify_relevant_laws", return_value=["BGB"]),
        patch("rag.fetch_law_content", return_value=fake_law),
    ):
        rag.client.messages.stream.return_value = _make_mock_stream(["Antwort."])
        events = asyncio.run(
            _collect(rag.stream_answer("Was ist ein Kaufvertrag?", [], "de"))
        )

    types = [e["type"] for e in events]
    assert "content" in types
    assert "sources" in types
    assert "done" in types
    content = "".join(e["content"] for e in events if e["type"] == "content")
    assert "Antwort." in content


def test_stream_answer_uses_fallback_when_no_relevant_laws():
    rag = make_rag()

    fake_law = {
        "abbreviation": "BGB",
        "title": "Bürgerliches Gesetzbuch",
        "url": "https://www.gesetze-im-internet.de/bgb/",
        "sections": [],
        "content": "Inhalt",
    }

    with (
        patch.object(rag, "_identify_relevant_laws", return_value=[]),
        patch("rag.fetch_law_content", return_value=fake_law),
    ):
        rag.client.messages.stream.return_value = _make_mock_stream(["Fallback."])
        events = asyncio.run(_collect(rag.stream_answer("Frage", [], "en")))

    assert any(e["type"] == "done" for e in events)
