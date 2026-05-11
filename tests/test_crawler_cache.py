import json
import time
from unittest.mock import patch

import crawler


def test_fetch_law_index_returns_cached_data(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(crawler, "LAW_INDEX_FILE", tmp_path / "law_index.json")

    sample = [
        {
            "abbreviation": "BGB",
            "title": "Test",
            "url": "https://x.com/",
            "path": "/bgb/",
        }
    ]
    (tmp_path / "law_index.json").write_text(json.dumps(sample))

    result = crawler.fetch_law_index()
    assert result == sample


def test_fetch_law_content_returns_cached_data(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "CACHE_DIR", tmp_path)

    cached = {
        "abbreviation": "BGB",
        "title": "Bürgerliches Gesetzbuch",
        "url": "https://x.com/bgb/",
        "sections": [],
        "content": "Inhalt",
    }
    (tmp_path / "law_bgb.json").write_text(json.dumps(cached))

    result = crawler.fetch_law_content("BGB", "https://x.com/bgb/")
    assert result == cached


def test_fetch_law_content_fetches_when_cache_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "CACHE_DIR", tmp_path)

    cache_file = tmp_path / "law_bgx.json"
    cache_file.write_text(json.dumps({"abbreviation": "BGX"}))
    # Make the file appear 8 days old
    old_mtime = time.time() - 8 * 86400
    import os

    os.utime(cache_file, (old_mtime, old_mtime))

    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = Exception(
            "network error"
        )
        result = crawler.fetch_law_content("BGX", "https://x.com/bgx/")

    assert result["abbreviation"] == "BGX"
    assert "error" in result


def test_fetch_law_content_returns_error_dict_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "CACHE_DIR", tmp_path)

    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = Exception(
            "timeout"
        )
        result = crawler.fetch_law_content("BGX", "https://x.com/bgx/")

    assert result["abbreviation"] == "BGX"
    assert "error" in result
    assert result["sections"] == []
