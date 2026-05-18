import json
import re
import asyncio
from typing import AsyncGenerator, cast
import anthropic
import structlog
from anthropic.types import MessageParam
from crawler import fetch_law_index, fetch_law_content, search_index

logger = structlog.get_logger()

SYSTEM_PROMPT = """Du bist Paragraphenreiter – ein präziser Rechtsauskunfts-Assistent für deutsches Recht.

Antworte DIREKT und KURZ auf die Frage. Keine Einleitung, keine Wiederholung der Frage.

Regeln für die Antwort:
- Füge Gesetzeslinks direkt im Fließtext ein, unmittelbar nach dem Paragraphen, im Format: [§ 433 BGB](https://www.gesetze-im-internet.de/bgb/__433.html)
- Nutze IMMER die EXAKTEN Paragraph-URLs aus dem Abschnitt "Paragraph-URLs" im bereitgestellten Kontext (z.B. https://www.gesetze-im-internet.de/bgb/__433.html), NIEMALS die allgemeine Gesetzes-URL
- Maximal 3-5 Sätze, außer bei komplexen Themen

Beispiel-Format:
Nach [§ 433 BGB](https://www.gesetze-im-internet.de/bgb/__433.html) ist der Verkäufer verpflichtet, dem Käufer die Sache zu übergeben. ..."""


class ParagraphenreiterRAG:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.law_index: list[dict] = []

    async def initialize(self):
        loop = asyncio.get_running_loop()
        self.law_index = await loop.run_in_executor(None, fetch_law_index)
        logger.info("index_loaded", law_count=len(self.law_index))

    def _filter_sections(
        self, sections: list[dict], question: str, top_n: int = 30
    ) -> list[dict]:
        """Return all sections whose titles match any question keyword, sorted by score."""
        tokens = set(re.findall(r"\w{3,}", question.lower()))
        scored = [(sum(1 for t in tokens if t in s["text"].lower()), s) for s in sections]
        scored.sort(key=lambda x: -x[0])
        relevant = [s for score, s in scored if score > 0]
        return relevant if relevant else sections[:top_n]

    def _suggest_abbreviations_from_knowledge(self, question: str) -> list[str]:
        """Ask Claude Haiku which laws are relevant, bypassing keyword title-matching."""
        prompt = f"""Welche deutschen Gesetze (Abkürzungen) sind am wahrscheinlichsten relevant für diese Rechtsfrage?

Frage: {question}

Antworte NUR mit einer JSON-Liste von bis zu 5 Abkürzungen, z.B.: ["BGB", "KSchG"]
Keine weiteren Erklärungen."""

        try:
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            block = resp.content[0]
            text = (block.text if hasattr(block, "text") else "").strip()
            m = re.search(r"\[.*?\]", text, re.DOTALL)
            if m:
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

        # Step 1: knowledge-based suggestion + keyword search in parallel
        loop = asyncio.get_running_loop()
        suggested_abbrevs, keyword_candidates = await asyncio.gather(
            loop.run_in_executor(
                None, self._suggest_abbreviations_from_knowledge, question
            ),
            loop.run_in_executor(None, search_index, question, self.law_index, 30),
        )

        abbrev_map = {law["abbreviation"].upper(): law for law in self.law_index}

        # Build final list: Haiku suggestions first, then keyword results to fill up to 5
        seen: set[str] = set()
        relevant_laws: list[dict] = []

        for abbrev in suggested_abbrevs:
            upper = abbrev.upper()
            law = abbrev_map.get(upper)
            if law and upper not in seen:
                relevant_laws.append(law)
                seen.add(upper)

        for law in keyword_candidates:
            if len(relevant_laws) >= 5:
                break
            upper = law["abbreviation"].upper()
            if upper not in seen:
                relevant_laws.append(law)
                seen.add(upper)

        if not relevant_laws:
            relevant_laws = keyword_candidates[:5] or [
                l for l in self.law_index[:5]
            ]

        logger.info(
            "laws_selected",
            suggested=suggested_abbrevs,
            final=[l["abbreviation"] for l in relevant_laws],
        )

        # Step 2: Fetch law contents
        law_contents = []
        sources = []
        for law_meta in relevant_laws:
            abbrev = law_meta["abbreviation"]
            yield sse("status", {"content": f"Lade {abbrev} von gesetze-im-internet.de…"})
            content = await loop.run_in_executor(
                None, fetch_law_content, abbrev, law_meta["url"]
            )
            law_contents.append(content)
            sources.append(
                {
                    "abbreviation": abbrev,
                    "title": content["title"],
                    "url": law_meta["url"],
                    "sections": content.get("sections", [])[:10],
                }
            )

        yield sse("status", {"content": "Generiere Antwort…"})

        # Step 3: Build context for Claude
        law_context = ""
        debug_laws = []
        for lc in law_contents:
            law_context += f"\n\n=== {lc['abbreviation']} – {lc['title']} ===\n"
            law_context += f"URL: {lc['url']}\n"
            sections = self._filter_sections(lc.get("sections", []), question)
            if sections:
                law_context += "Paragraph-URLs:\n"
                for s in sections:
                    law_context += f"  {s['text']}: {s['url']}\n"
            content_slice = lc["content"][:4000]
            law_context += content_slice
            debug_laws.append({
                "abbreviation": lc["abbreviation"],
                "title": lc["title"],
                "url": lc["url"],
                "sections_used": len(sections),
                "content_chars": len(content_slice),
            })

        logger.debug("context_laws", laws=debug_laws)
        yield sse("debug", {"laws": debug_laws})

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

        # Step 4: Stream the answer
        full_answer = ""
        with self.client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=cast(list[MessageParam], messages),
        ) as stream:
            for text in stream.text_stream:
                full_answer += text
                yield sse("content", {"content": text})

        yield sse("sources", {"sources": sources})
        yield sse("done", {})
