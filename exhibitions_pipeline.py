# exhibitions_pipeline.py
import asyncio, time, json, re, os, hashlib
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser
from pydantic import BaseModel, Field, ValidationError
from dateutil import parser as dateparse
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -------------------- Models & utils --------------------

@dataclass
class Exhibition:
    title: str
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

class ExhibitionListItem(BaseModel):
    title: str
    href: str
    date_text: Optional[str] = None

class ExhibitionRecord(BaseModel):
    title: str
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def normalize_title_key(title: Optional[str]) -> str:
    if not title: return ""
    t = strip_accents(title).casefold()
    t = re.sub(r"[^\w\s-]", "", t)
    return norm_space(t)

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

# -------------------- Condenser --------------------

class PageCondenser:
    ALLOWED_TEXT_TAGS = {"h1","h2","h3","h4","p","li","time","figcaption"}
    MAIN_SELECTORS = ["main", "#content", "#swup", "[role=main]", "article", ".content", ".exhibitions", "#exhibitions"]

    def __init__(self, cache_dir=".cache_html", timeout=20.0, http2=True):
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(exist_ok=True)
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            http2=http2,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Exhibitions/1.1)"},
            timeout=self.timeout,
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_html(self, url: str, use_cache=True) -> Tuple[str, bool, float]:
        start = time.perf_counter()
        key = self.cache_dir / (sha1(url) + ".html")
        if use_cache and key.exists():
            html = key.read_text(encoding="utf-8", errors="ignore")
            return html, True, (time.perf_counter() - start) * 1000
        r = await self.client.get(url)
        r.raise_for_status()
        html = r.text
        if use_cache:
            key.write_text(html, encoding="utf-8")
        return html, False, (time.perf_counter() - start) * 1000

    @staticmethod
    def _choose_main(root: HTMLParser) -> HTMLParser:
        for sel in PageCondenser.MAIN_SELECTORS:
            node = root.css_first(sel)
            if node: return node
        return root

    @staticmethod
    def _same_domain(href: str, base: str) -> bool:
        try:
            netloc = urlparse(href).netloc
            return netloc in ("", urlparse(base).netloc)
        except Exception:
            return True

    @staticmethod
    def _nearest_context(a_node):
        hops, node = 0, a_node.parent
        while node and hops < 4:
            t = norm_space(node.text())
            if len(t) >= 40:
                return t[:240]
            node = node.parent
            hops += 1
        return ""

    @staticmethod
    def _classify_anchor(a):
        text = (a["text"] + " " + a.get("context","")).lower()
        href = a["href"].lower()
        is_event = ("calendar" in href) or (re.search(r"\bevent(s)?\b", text))
        is_exhibition = (("exhibit" in text) or ("exhibition" in text) or ("/exhibitions" in href)) and not is_event
        is_pager = bool(re.search(r"\b(next|more|see all|load more|view all|past exhibitions|previous)\b", text))
        return ("exhibition" if is_exhibition else "event" if is_event else "other",
                "pagination" if is_pager else None)

    @staticmethod
    def _take_text(node, limit_chars=16000) -> str:
        lines, count = [], 0
        for tag in PageCondenser.ALLOWED_TEXT_TAGS:
            for el in node.css(tag):
                t = norm_space(el.text())
                if not t: continue
                lines.append(t); count += len(t) + 1
                if count >= limit_chars:
                    return "\n".join(lines)[:limit_chars]
        text = norm_space(node.text())[:limit_chars]
        return "\n".join(lines) if lines else text

    def _anchors_from(self, node, base_url, max_items=1000) -> List[Dict[str, Any]]:
        seen, out = set(), []
        for a in node.css("a"):
            href = (a.attributes.get("href") or "").strip()
            text = norm_space(a.text())[:180]
            if not href or not text: continue
            href = urljoin(base_url, href)
            if not self._same_domain(href, base_url) and "exhibition" not in text.lower():
                continue
            key = (href, text.lower())
            if key in seen: continue
            seen.add(key)
            rec = {"text": text, "href": href, "context": self._nearest_context(a)}
            kind, pager = self._classify_anchor(rec)
            rec["kind"], rec["pager"] = kind, pager
            out.append(rec)
            if len(out) >= max_items: break
        return out

    def condense_html(self, html: str, base_url: str, limit_text_chars=16000) -> Dict[str, Any]:
        doc = HTMLParser(html)
        body = doc.body or doc
        main = self._choose_main(body)
        for sel in ("script", "style", "noscript", "template", "svg", "iframe"):
            for n in main.css(sel):
                n.decompose()
        anchors = self._anchors_from(main, base_url)
        text = self._take_text(main, limit_chars=limit_text_chars)
        return {"text": text, "anchors": anchors, "html_chars": len(html), "text_chars": len(text)}

    async def condense_url(self, url: str, use_cache=True, limit_text_chars=16000) -> Dict[str, Any]:
        html, cached, t_fetch = await self.fetch_html(url, use_cache=use_cache)
        t0 = time.perf_counter()
        result = self.condense_html(html, url, limit_text_chars=limit_text_chars)
        t_condense = (time.perf_counter() - t0) * 1000
        result["timing"] = {
            "t_fetch_ms": round(t_fetch,1),
            "t_condense_ms": round(t_condense,1),
            "t_total_ms": round(t_fetch + t_condense,1),
            "from_cache": cached
        }
        result["url"] = url
        return result

# -------------------- LLM Extractor --------------------

class LLMExtractor:
    def __init__(self, model_listing="gpt-5-mini", model_detail="gpt-5-mini"):
        self.client = OpenAI()
        self.model_listing = model_listing
        self.model_detail = model_detail

    def _call_json(self, model: str, prompt: str) -> Dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type":"json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    def extract_listing(self, museum_name: str, listing_text: str, anchors: List[Dict[str,Any]]) -> List[ExhibitionListItem]:
        # keep only likely exhibition anchors for the LLM context
        ex_anchors = [a for a in anchors if a.get("kind") == "exhibition"]
        # reduce token drift: pass the top N anchors and a small slice of text
        anchors_json = json.dumps(ex_anchors[:80], ensure_ascii=False)
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
        items = []
        for it in data.get("items", []):
            try:
                items.append(ExhibitionListItem(**it))
            except ValidationError:
                continue
        return items

    def extract_detail(self, museum_name: str, detail_text: str, url: str) -> ExhibitionRecord:
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
            return ExhibitionRecord(**data)
        except ValidationError:
            # minimal fallback with title if present
            title = data.get("title") or ""
            return ExhibitionRecord(title=title, museum=museum_name, url=url)

# -------------------- Orchestrator --------------------

class ExhibitionsOrchestrator:
    def __init__(self, condenser: PageCondenser, llm: LLMExtractor,
                 follow_pagination=True, detail_concurrency=10, cache=True):
        self.c = condenser
        self.llm = llm
        self.follow_pagination = follow_pagination
        self.semaphore = asyncio.Semaphore(detail_concurrency)
        self.cache = cache

    async def _get_listing_bundle(self, museum_url: str) -> Dict[str, Any]:
        base_bundle = await self.c.condense_url(museum_url, use_cache=self.cache)
        bundles = [base_bundle]
        if self.follow_pagination:
            pagers = [a for a in base_bundle["anchors"] if a.get("pager")]
            # follow up to 3 pagination links to avoid explosion
            for a in pagers[:3]:
                try:
                    b = await self.c.condense_url(a["href"], use_cache=self.cache)
                    bundles.append(b)
                except Exception:
                    continue
        # merge anchors + take longest text
        anchors = []
        text_chunks = []
        for b in bundles:
            anchors.extend(b["anchors"])
            text_chunks.append(b["text"])
        merged = {
            "text": "\n".join(text_chunks)[:16000],
            "anchors": anchors,
            "timing": base_bundle["timing"],
            "url": museum_url
        }
        return merged

    async def _fetch_detail_and_extract(self, museum_name: str, href: str, timings: Dict[str, Any]) -> Optional[Exhibition]:
        async with self.semaphore:
            t0 = time.perf_counter()
            try:
                bundle = await self.c.condense_url(href, use_cache=self.cache)
            except Exception:
                timings[href] = {"status": "fetch_error"}
                return None
            t_fetch_total = bundle["timing"]["t_total_ms"]
            t1 = time.perf_counter()
            rec = self.llm.extract_detail(museum_name, bundle["text"], href)
            t_llm = (time.perf_counter() - t1) * 1000
            timings[href] = {
                "status": "ok",
                "t_fetch_ms": round(t_fetch_total,1),
                "t_llm_ms": round(t_llm,1),
                "html_chars": bundle["html_chars"],
                "text_chars": bundle["text_chars"],
                "from_cache": bundle["timing"]["from_cache"]
            }
            return Exhibition(**rec.dict())

    async def run_for_museum(self, museum_name: str, listing_url: str) -> Dict[str, Any]:
        overall_start = time.perf_counter()
        listing_bundle = await self._get_listing_bundle(listing_url)
        t_listing = listing_bundle["timing"]

        # LLM: pick exhibitions from anchors
        t0 = time.perf_counter()
        items = self.llm.extract_listing(museum_name, listing_bundle["text"], listing_bundle["anchors"])
        t_llm_listing = (time.perf_counter() - t0) * 1000

        # Dedup by href
        seen = set(); todo = []
        for it in items:
            href = it.href
            if href in seen: continue
            seen.add(href); todo.append(it)

        # Fetch details concurrently
        per_page_timings: Dict[str, Any] = {}
        coros = [self._fetch_detail_and_extract(museum_name, it.href, per_page_timings) for it in todo]
        results = await asyncio.gather(*coros)

        # Dedup by normalized title & fill museum
        uniq, titles_seen = [], set()
        for ex in results:
            if not ex or not ex.title: continue
            ex.museum = museum_name
            key = normalize_title_key(ex.title)
            if key in titles_seen: continue
            titles_seen.add(key); uniq.append(ex)

        overall_ms = (time.perf_counter() - overall_start) * 1000
        summary = {
            "museum": museum_name,
            "listing_url": listing_url,
            "counts": {
                "todo": len(todo),
                "scraped": len([x for x in results if x]),
                "unique": len(uniq)
            },
            "timing_ms": {
                "listing_fetch": t_listing["t_total_ms"],
                "listing_llm": round(t_llm_listing,1),
                "overall": round(overall_ms,1)
            },
            "per_page": per_page_timings
        }
        return {"summary": summary, "exhibitions": [asdict(x) for x in uniq]}

# -------------------- CLI / Example --------------------

async def main():
    museums = [
        {"name": "National Gallery of Ireland", "url": "https://www.nationalgallery.ie/art-and-artists/exhibitions"},
        # {"name": "The Met", "url": "https://www.metmuseum.org/exhibitions"},
        # {"name": "Fine Arts Museums of San Francisco", "url": "https://www.famsf.org/whats-on"},
    ]

    condenser = PageCondenser()
    llm = LLMExtractor(model_listing="gpt-5-mini", model_detail="gpt-5-mini")
    orch = ExhibitionsOrchestrator(condenser, llm, follow_pagination=True, detail_concurrency=12, cache=True)

    all_out = {"runs": [], "exhibitions": []}
    try:
        for m in museums:
            print(f"\n=== {m['name']} ===")
            result = await orch.run_for_museum(m["name"], m["url"])
            # logging
            s = result["summary"]
            print(f"Listing fetch: {s['timing_ms']['listing_fetch']} ms | LLM(listing): {s['timing_ms']['listing_llm']} ms | Overall: {s['timing_ms']['overall']} ms")
            print(f"Found {s['counts']['todo']} candidates → {s['counts']['scraped']} details → {s['counts']['unique']} unique exhibitions")
            # per-page timings
            slow = sorted(s["per_page"].items(), key=lambda kv: (kv[1].get("t_fetch_ms",0)+kv[1].get("t_llm_ms",0)), reverse=True)[:5]
            for url, t in slow:
                if t.get("status")=="ok":
                    print(f"  · {url} | fetch {t['t_fetch_ms']} ms, llm {t['t_llm_ms']} ms, text {t['text_chars']} chars")
            all_out["runs"].append(s)
            all_out["exhibitions"].extend(result["exhibitions"])
    finally:
        await condenser.close()

    # Save artifacts
    out_dir = Path("out"); out_dir.mkdir(exist_ok=True)
    Path(out_dir / "exhibitions.json").write_text(json.dumps(all_out["exhibitions"], indent=2, ensure_ascii=False), encoding="utf-8")
    Path(out_dir / "runs_summary.json").write_text(json.dumps(all_out["runs"], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: out/exhibitions.json ({len(all_out['exhibitions'])} records), out/runs_summary.json")

if __name__ == "__main__":
    asyncio.run(main())
