import time, json
from typing import Dict, Any, List
from pydantic import ValidationError
from openai import OpenAI

from backend.scraper.models import ExhibitionListItem, ExhibitionRecord

class LLMExtractor:
    def __init__(self, model_listing="gpt-5-mini", model_detail="gpt-5-mini"):
        self.client = OpenAI(timeout=30.0, max_retries=2)
        self.model_listing = model_listing
        self.model_detail = model_detail

    def _call_json(self, model: str, prompt: str) -> Dict[str, Any]:
        print(f"[LLM] Making API call to {model} (prompt length: {len(prompt)} chars)")
        t_start = time.perf_counter()
        
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type":"json_object"},
                timeout=90.0,
            )
            
            elapsed = (time.perf_counter() - t_start) * 1000
            content = resp.choices[0].message.content
            print(f"[LLM] API call completed in {elapsed:.1f}ms (response: {len(content)} chars)")
            
            result = json.loads(content)
            print(f"[LLM] JSON parsing successful")
            return result
            
        except Exception as e:
            elapsed = (time.perf_counter() - t_start) * 1000
            print(f"[LLM] ERROR: API call failed after {elapsed:.1f}ms: {e}")
            raise

    def extract_listing(self, museum_name: str, listing_text: str, anchors: List[Dict[str,Any]]) -> List[ExhibitionListItem]:
        print(f"[LLM_LISTING] Starting extraction for {museum_name}")
        print(f"[LLM_LISTING] Input: {len(anchors)} total anchors, {len(listing_text)} chars text")
        
        # keep only likely exhibition anchors for the LLM context
        ex_anchors = [a for a in anchors if a.get("kind") == "exhibition"]
        print(f"[LLM_LISTING] Filtered to {len(ex_anchors)} exhibition anchors")
        
        # reduce token drift: pass the top N anchors and a small slice of text
        top_anchors = ex_anchors[:80]
        anchors_json = json.dumps(top_anchors, ensure_ascii=False)
        print(f"[LLM_LISTING] Using top {len(top_anchors)} anchors for LLM context")
        prompt = f"""
You are given condensed page TEXT and candidate exhibition ANCHORS from the museum listing page for "{museum_name}".

Return ONLY current or upcoming exhibitions that a visitor can click into (ignore Events, Calendar, Membership, News).
Extract from the ANCHORS primarily; use TEXT only when it clarifies titles/dates.

Output JSON:
{{"items":[{{"title": "...", "href":"...", "date_text":"..."}}]}}

TEXT (truncated):
{listing_text[:8000]}

ANCHORS (top 80):
{anchors_json}
"""
        data = self._call_json(self.model_listing, prompt)
        
        raw_items = data.get("items", [])
        print(f"[LLM_LISTING] LLM returned {len(raw_items)} raw items")
        
        items = []
        validation_errors = 0
        for i, it in enumerate(raw_items):
            try:
                items.append(ExhibitionListItem(**it))
                print(f"[LLM_LISTING] Item {i+1}: '{it.get('title', 'NO_TITLE')}'")
            except ValidationError as e:
                validation_errors += 1
                print(f"[LLM_LISTING] Validation error for item {i+1}: {e}")
                continue
        
        if validation_errors > 0:
            print(f"[LLM_LISTING] Warning: {validation_errors} items failed validation")
        
        print(f"[LLM_LISTING] Successfully extracted {len(items)} valid exhibition items")
        return items

    def extract_detail(self, museum_name: str, detail_text: str, url: str) -> ExhibitionRecord:
        print(f"[LLM_DETAIL] Extracting details for: {url}")
        print(f"[LLM_DETAIL] Input text length: {len(detail_text)} chars")
        
        prompt = f"""
Extract a single exhibition record for museum "{museum_name}" from the following TEXT.
Be concise; if a field is unknown leave it null. Dates should be explicit like "9 October 2025".

Output JSON:
{{
  "title": "...",
  "main_artist": "... or null",
  "other_artists": ["..."] or [],
  "start_date": "... or null",
  "end_date": "... or null",
  "museum": "{museum_name}",
  "details": "1-2 sentence summary or null",
  "url": "{url}"
}}

TEXT (truncated to 10k chars):
{detail_text[:10000]}
"""
        data = self._call_json(self.model_detail, prompt)
        
        try:
            record = ExhibitionRecord(**data)
            print(f"[LLM_DETAIL] Successfully extracted: '{record.title}'")
            if record.main_artist:
                print(f"[LLM_DETAIL] Main artist: {record.main_artist}")
            if record.start_date or record.end_date:
                print(f"[LLM_DETAIL] Dates: {record.start_date} to {record.end_date}")
            return record
            
        except ValidationError as e:
            print(f"[LLM_DETAIL] Validation error: {e}")
            # minimal fallback with title if present
            title = data.get("title") or ""
            print(f"[LLM_DETAIL] Using fallback record with title: '{title}'")
