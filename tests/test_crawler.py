from crawler import search_index

INDEX = [
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


def test_exact_abbreviation_ranks_first():
    results = search_index("Was regelt das BGB?", INDEX)
    assert results, "Expected at least one result"
    assert results[0]["abbreviation"] == "BGB"


def test_keyword_in_title_matches():
    results = search_index("Strafrecht", INDEX)
    assert any(r["abbreviation"] == "StGB" for r in results)


def test_multiple_abbreviations_both_present():
    results = search_index("BGB HGB Kaufvertrag", INDEX)
    abbrevs = {r["abbreviation"] for r in results}
    assert "BGB" in abbrevs
    assert "HGB" in abbrevs


def test_stopwords_alone_return_empty():
    results = search_index("die der das und oder", INDEX)
    assert results == []


def test_unrelated_query_returns_empty():
    results = search_index("xyz unbekannt foobar", INDEX)
    assert results == []


def test_top_n_limits_results():
    large_index = [
        {
            "abbreviation": f"LAW{i}",
            "title": f"Gesetz nummer {i}",
            "url": "",
            "path": "",
        }
        for i in range(50)
    ]
    results = search_index("Gesetz nummer", large_index, top_n=5)
    assert len(results) <= 5


def test_empty_index_returns_empty():
    assert search_index("BGB Kaufvertrag", []) == []


def test_empty_query_returns_empty():
    assert search_index("", INDEX) == []
