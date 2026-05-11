import json
from unittest.mock import patch


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["index_ready"] is True


def test_config_returns_null_when_unset(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {"legal_notice_url": None}


def test_config_returns_url_when_set(client, monkeypatch):
    monkeypatch.setenv("LEGAL_NOTICE_URL", "https://example.com/impressum")
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["legal_notice_url"] == "https://example.com/impressum"


def test_index_status_ready(client):
    response = client.get("/api/index/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["law_count"] == 5  # SAMPLE_INDEX in conftest has 5 entries


def test_chat_rejects_empty_message(client):
    response = client.post("/api/chat", json={"message": "", "language": "de"})
    assert response.status_code == 422


def test_chat_rejects_message_too_long(client):
    response = client.post("/api/chat", json={"message": "x" * 2001, "language": "de"})
    assert response.status_code == 422


def test_chat_rejects_invalid_language(client):
    response = client.post("/api/chat", json={"message": "Frage", "language": "xx"})
    assert response.status_code == 422


def test_chat_rejects_invalid_role(client):
    response = client.post(
        "/api/chat",
        json={
            "message": "Frage",
            "history": [{"role": "system", "content": "hack"}],
            "language": "de",
        },
    )
    assert response.status_code == 422


def test_chat_streams_event_stream(client):
    async def fake_stream(question, history, language):
        yield f"data: {json.dumps({'type': 'content', 'content': 'Testantwort.'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    with patch("app.rag.stream_answer", side_effect=fake_stream):
        response = client.post(
            "/api/chat",
            json={"message": "Was ist das BGB?", "history": [], "language": "de"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "Testantwort." in response.text
