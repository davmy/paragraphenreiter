import httpx
import json
import time
import re
from pathlib import Path
from bs4 import BeautifulSoup

CACHE_DIR = Path("cache")
LAW_INDEX_FILE = CACHE_DIR / "law_index.json"
BASE_URL = "https://www.gesetze-im-internet.de"
HEADERS = {
    "User-Agent": "Paragraphenreiter/1.0 (Legal research chatbot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}


def fetch_law_index(force_refresh: bool = False) -> list[dict]:
    CACHE_DIR.mkdir(exist_ok=True)
    if not force_refresh and LAW_INDEX_FILE.exists():
        age = time.time() - LAW_INDEX_FILE.stat().st_mtime
        if age < 86400:  # 24 h cache
            with open(LAW_INDEX_FILE, encoding="utf-8") as f:
                return json.load(f)

    laws = []
    seen = set()
    # aktuell.html links to Teilliste_A.html … Teilliste_Z.html and Teilliste_1.html …
    sublists = (
        [f"Teilliste_{c}.html" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        + [f"Teilliste_{n}.html" for n in range(10)]
    )

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for sublist in sublists:
            try:
                resp = client.get(f"{BASE_URL}/{sublist}")
                resp.raise_for_status()
            except Exception:
                continue
            # Site declares utf-8 but actually serves iso-8859-1
            soup = BeautifulSoup(resp.content, "lxml", from_encoding="iso-8859-1")

            # Each law entry: <a href="./path/index.html"><abbr title="Full Title">ABBREV</abbr></a>
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not re.search(r"/index\.html$", href):
                    continue
                # Extract abbreviation and full title from <abbr> child
                abbr_el = a.find("abbr")
                if abbr_el:
                    abbrev = abbr_el.get_text(strip=True)
                    title = abbr_el.get("title", abbrev)
                else:
                    abbrev = a.get_text(strip=True)
                    title = abbrev
                if not abbrev or len(abbrev) < 1:
                    continue
                abbrev_key = abbrev.upper().replace(" ", "")
                if abbrev_key in seen:
                    continue
                seen.add(abbrev_key)
                # Build absolute URL: href is like ./bgb/index.html
                clean_path = href.lstrip("./")
                law_url = f"{BASE_URL}/{clean_path.split('/')[0]}/"
                laws.append({
                    "abbreviation": abbrev.strip(),
                    "title": title.strip(),
                    "url": law_url,
                    "path": f"/{clean_path.split('/')[0]}/",
                })

    with open(LAW_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(laws, f, ensure_ascii=False, indent=2)

    return laws


def search_index(query: str, law_index: list[dict], top_n: int = 30) -> list[dict]:
    """Keyword-based pre-filter: score laws by how many query tokens appear in title."""
    query_lower = query.lower()
    # Also look for explicit abbreviations mentioned in query
    abbrev_pattern = re.compile(r"\b([A-Z]{2,8})\b")
    mentioned_abbrevs = {m.upper() for m in abbrev_pattern.findall(query)}

    tokens = re.findall(r"\w+", query_lower)
    stopwords = {"die", "der", "das", "und", "oder", "ich", "ein", "eine", "einen",
                 "was", "wie", "wo", "wann", "warum", "ist", "sind", "hat", "haben",
                 "kann", "darf", "muss", "soll", "in", "an", "auf", "bei", "von",
                 "zu", "mit", "nach", "über", "für", "gegen", "um", "aus", "als"}
    tokens = [t for t in tokens if t not in stopwords and len(t) > 2]

    scored = []
    for law in law_index:
        score = 0
        title_lower = law["title"].lower()
        abbrev = law["abbreviation"].upper()

        # Explicit abbreviation mention → highest priority
        if abbrev in mentioned_abbrevs:
            score += 100

        for token in tokens:
            if token in title_lower:
                score += 1
            # Partial match bonus
            if len(token) > 4 and token[:4] in title_lower:
                score += 0.5

        if score > 0:
            scored.append((score, law))

    scored.sort(key=lambda x: -x[0])
    return [law for _, law in scored[:top_n]]


def fetch_law_content(abbreviation: str, url: str) -> dict:
    cache_file = CACHE_DIR / f"law_{abbreviation.lower()}.json"

    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 604800:  # 7-day cache for law content
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)

    try:
        with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "lxml", from_encoding="iso-8859-1")

        # Title
        title_el = soup.find("h1") or soup.find("h2")
        title = title_el.get_text(strip=True) if title_el else abbreviation

        # Collect paragraph links (§ references)
        sections = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if text and ("§" in text or "__" in href):
                full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                sections.append({"text": text, "url": full_url})

        # Extract readable law text (first ~8000 chars to stay within limits)
        content = ""
        for selector in ["div.jnnorm", "div#content", "main", "article"]:
            el = soup.select_one(selector)
            if el:
                content = el.get_text(separator="\n", strip=True)
                break
        if not content:
            content = "\n".join(p.get_text(strip=True) for p in soup.find_all("p")[:60])

        result = {
            "abbreviation": abbreviation,
            "title": title,
            "url": url,
            "sections": sections[:80],
            "content": content[:8000],
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    except Exception as e:
        return {
            "abbreviation": abbreviation,
            "title": abbreviation,
            "url": url,
            "sections": [],
            "content": f"Fehler beim Laden des Gesetzes: {e}",
            "error": str(e),
        }
