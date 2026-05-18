import os
from unittest.mock import MagicMock, patch

# Must be set before app.py is imported (it raises at module level if missing)
os.environ["ANTHROPIC_API_KEY"] = "sk-test"

# Patch anthropic.Anthropic before any module imports it
_patcher = patch("anthropic.Anthropic", return_value=MagicMock())
_patcher.start()

import pytest
from fastapi.testclient import TestClient

SAMPLE_INDEX = [
    {
        "abbreviation": "BGB",
        "title": "Bürgerliches Gesetzbuch",
        "url": "https://www.gesetze-im-internet.de/bgb/",
        "path": "/bgb/",
    },
    {
        "abbreviation": "StGB",
        "title": "Strafgesetzbuch",
        "url": "https://www.gesetze-im-internet.de/stgb/",
        "path": "/stgb/",
    },
    {
        "abbreviation": "HGB",
        "title": "Handelsgesetzbuch",
        "url": "https://www.gesetze-im-internet.de/hgb/",
        "path": "/hgb/",
    },
    {
        "abbreviation": "GG",
        "title": "Grundgesetz für die Bundesrepublik Deutschland",
        "url": "https://www.gesetze-im-internet.de/gg/",
        "path": "/gg/",
    },
    {
        "abbreviation": "AO",
        "title": "Abgabenordnung",
        "url": "https://www.gesetze-im-internet.de/ao_1977/",
        "path": "/ao_1977/",
    },
]


FAKE_LAW_CONTENT = {
    "abbreviation": "BGB",
    "title": "Bürgerliches Gesetzbuch",
    "url": "https://www.gesetze-im-internet.de/bgb/",
    "sections": [
        {"text": "§ 433", "url": "https://www.gesetze-im-internet.de/bgb/__433.html"}
    ],
    "content": "Testinhalt",
}


@pytest.fixture(scope="session")
def client():
    # Prevent lifespan and request handlers from hitting the network
    with (
        patch("rag.fetch_law_index", return_value=SAMPLE_INDEX),
        patch("rag.fetch_law_content", return_value=FAKE_LAW_CONTENT),
        patch("rag.search_index", return_value=SAMPLE_INDEX[:2]),
    ):
        from app import app

        with TestClient(app) as c:
            yield c
