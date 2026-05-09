import json
import asyncio
from typing import AsyncGenerator
import anthropic
from crawler import fetch_law_index, fetch_law_content, search_index

SYSTEM_PROMPT = """Du bist Paragraphenreiter – ein präziser Rechtsauskunfts-Assistent für deutsches Recht.

Antworte DIREKT und KURZ auf die Frage. Keine Einleitung, keine Wiederholung der Frage.

Regeln für die Antwort:
- Füge Gesetzeslinks direkt im Fließtext ein, unmittelbar nach dem Paragraphen, im Format: [§ 433 BGB](https://www.gesetze-im-internet.de/bgb/__433.html)
- Nutze IMMER die EXAKTEN Paragraph-URLs aus dem Abschnitt "Paragraph-URLs" im bereitgestellten Kontext (z.B. https://www.gesetze-im-internet.de/bgb/__433.html), NIEMALS die allgemeine Gesetzes-URL
- Maximal 3-5 Sätze, außer bei komplexen Themen
- Am Ende: genau eine Zeile: ⚠️ *Kein Ersatz für Rechtsberatung.*

Beispiel-Format:
Nach [§ 433 BGB](https://www.gesetze-im-internet.de/bgb/__433.html) ist der Verkäufer verpflichtet, dem Käufer die Sache zu übergeben. ..."""


class ParagraphenreiterRAG:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.law_index: list[dict] = []

    async def initialize(self):
        loop = asyncio.get_event_loop()
        self.law_index = await loop.run_in_executor(None, fetch_law_index)
        print(f"[RAG] Gesetzesindex geladen: {len(self.law_index)} Gesetze")

    def _build_index_summary(self, candidates: list[dict]) -> str:
        lines = [f"- {l['abbreviation']}: {l['title']}" for l in candidates]
        return "\n".join(lines)

    def _identify_relevant_laws(self, question: str, candidates: list[dict]) -> list[str]:
        if not candidates:
            return []

        index_text = self._build_index_summary(candidates)
        prompt = f"""Welche der folgenden deutschen Gesetze sind am relevantesten für diese Rechtsfrage?

Frage: {question}

Verfügbare Gesetze:
{index_text}

Antworte NUR mit einer JSON-Liste der Abkürzungen der 3-5 relevantesten Gesetze, z.B.: ["BGB", "HGB"]
Keine weiteren Erklärungen."""

        resp = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Extract JSON list from response
        import re
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return []

    async def stream_answer(
        self,
        question: str,
        history: list[dict],
        language: str = "de",
    ) -> AsyncGenerator[str, None]:
        def sse(event_type: str, data: dict) -> str:
            return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"

        yield sse("status", {"content": "Durchsuche Gesetzesindex…"})

        # Step 1: keyword pre-filter
        loop = asyncio.get_event_loop()
        candidates = await loop.run_in_executor(
            None, search_index, question, self.law_index, 30
        )

        if not candidates:
            candidates = self.law_index[:30]

        yield sse("status", {"content": f"{len(candidates)} potenzielle Gesetze gefunden – identifiziere relevante…"})

        # Step 2: Claude selects the best laws
        relevant_abbrevs = await loop.run_in_executor(
            None, self._identify_relevant_laws, question, candidates
        )

        if not relevant_abbrevs:
            # Fallback: use top 3 keyword candidates
            relevant_abbrevs = [c["abbreviation"] for c in candidates[:3]]

        # Build lookup map
        abbrev_map = {l["abbreviation"]: l for l in self.law_index}

        # Step 3: Fetch law contents
        law_contents = []
        sources = []
        for abbrev in relevant_abbrevs[:5]:
            law_meta = abbrev_map.get(abbrev.upper())
            if not law_meta:
                continue
            yield sse("status", {"content": f"Lade {abbrev} von gesetze-im-internet.de…"})
            content = await loop.run_in_executor(
                None, fetch_law_content, abbrev, law_meta["url"]
            )
            law_contents.append(content)
            sources.append({
                "abbreviation": abbrev,
                "title": content["title"],
                "url": law_meta["url"],
                "sections": content.get("sections", [])[:10],
            })

        yield sse("status", {"content": "Generiere Antwort…"})

        # Step 4: Build context for Claude
        law_context = ""
        for lc in law_contents:
            law_context += f"\n\n=== {lc['abbreviation']} – {lc['title']} ===\n"
            law_context += f"URL: {lc['url']}\n"
            sections = lc.get("sections", [])
            if sections:
                law_context += "Paragraph-URLs:\n"
                for s in sections:
                    law_context += f"  {s['text']}: {s['url']}\n"
            law_context += lc["content"][:4000]

        messages = []
        for h in history[-6:]:  # Last 3 turns
            messages.append({"role": h["role"], "content": h["content"]})

        lang_instruction = {
            "de": "Antworte auf Deutsch.",
            "en": "Answer in English.",
            "tr": "Türkçe yanıtla.",
            "ar": "أجب باللغة العربية.",
            "ru": "Отвечай на русском языке.",
            "uk": "Відповідай українською мовою.",
            "pl": "Odpowiedz po polsku.",
            "ro": "Răspunde în română.",
            "fr": "Réponds en français.",
            "es": "Responde en español.",
            "vi": "Trả lời bằng tiếng Việt.",
            "zh": "请用中文回答。",
        }.get(language, "Antworte auf Deutsch.")

        user_message = f"""Rechtsfrage: {question}

Relevante Gesetze aus gesetze-im-internet.de:
{law_context}

Bitte beantworte die Frage mit konkreten Paragraphen-Verweisen und Links zu gesetze-im-internet.de. {lang_instruction}"""
        messages.append({"role": "user", "content": user_message})

        # Step 5: Stream the answer
        full_answer = ""
        with self.client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_answer += text
                yield sse("content", {"content": text})

        yield sse("sources", {"sources": sources})
        yield sse("done", {})
