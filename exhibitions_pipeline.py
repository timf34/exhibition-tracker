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
    other_artists: Optional[List[str]] = Field(default_factory=list)
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
    # Include more tags where dates and info might hide (from v2)
    ALLOWED_TEXT_TAGS = {"h1","h2","h3","h4","p","li","time","figcaption","span","dt","dd","em","strong"}
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
        print(f"[FETCH] Starting fetch for: {url}")
        start = time.perf_counter()
        key = self.cache_dir / (sha1(url) + ".html")
        if use_cache and key.exists():
            print(f"[FETCH] Cache hit - loading from: {key.name}")
            html = key.read_text(encoding="utf-8", errors="ignore")
            elapsed = (time.perf_counter() - start) * 1000
            print(f"[FETCH] Cache load completed in {elapsed:.1f}ms ({len(html)} chars)")
            return html, True, elapsed
        
        print(f"[FETCH] Cache miss - making HTTP request")
        try:
            r = await self.client.get(url)
            r.raise_for_status()
            html = r.text
            print(f"[FETCH] HTTP request successful ({r.status_code}) - {len(html)} chars")
            if use_cache:
                key.write_text(html, encoding="utf-8")
                print(f"[FETCH] Cached to: {key.name}")
        except Exception as e:
            print(f"[FETCH] ERROR: Failed to fetch {url}: {e}")
            raise
        
        elapsed = (time.perf_counter() - start) * 1000
        print(f"[FETCH] Fetch completed in {elapsed:.1f}ms")
        return html, False, elapsed

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
        # Keep pagination detection but be less aggressive about filtering
        is_pager = bool(re.search(r"\b(next|more|see all|load more|view all|previous)\b", text))
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
    
    def _meta_descriptions(self, doc: HTMLParser) -> str:
        """Extract meta descriptions (from v2) to help find dates/summaries"""
        out = []
        for sel in [
            "meta[property='og:description']",
            "meta[name='og:description']",
            "meta[name='twitter:description']",
            "meta[name='description']",
        ]:
            try:
                m = doc.css_first(sel)
                if m:
                    c = m.attributes.get("content")
                    if c: out.append(norm_space(c))
            except Exception:
                pass
        return " ".join(out)

    def _anchors_from(self, node, base_url, max_items=1000) -> List[Dict[str, Any]]:
        seen, out = set(), []
        total_links = len(node.css("a"))
        skipped_counts = {"no_href_text": 0, "external": 0, "duplicate": 0}
        
        for a in node.css("a"):
            href = (a.attributes.get("href") or "").strip()
            text = norm_space(a.text())[:180]
            if not href or not text: 
                skipped_counts["no_href_text"] += 1
                continue
                
            href = urljoin(base_url, href)
            if not self._same_domain(href, base_url) and "exhibition" not in text.lower():
                skipped_counts["external"] += 1
                continue
                
            key = (href, text.lower())
            if key in seen: 
                skipped_counts["duplicate"] += 1
                continue
                
            seen.add(key)
            rec = {"text": text, "href": href, "context": self._nearest_context(a)}
            kind, pager = self._classify_anchor(rec)
            rec["kind"], rec["pager"] = kind, pager
            out.append(rec)
            if len(out) >= max_items: break
        
        if any(skipped_counts.values()):
            print(f"[CONDENSE] Link filtering: {total_links} total → {len(out)} kept (skipped: {skipped_counts['no_href_text']} no href/text, {skipped_counts['external']} external, {skipped_counts['duplicate']} duplicate)")
        
        return out

    def condense_html(self, html: str, base_url: str, limit_text_chars=16000) -> Dict[str, Any]:
        print(f"[CONDENSE] Starting HTML condensation ({len(html)} chars input)")
        t_start = time.perf_counter()
        
        doc = HTMLParser(html)
        body = doc.body or doc
        main = self._choose_main(body)
        print(f"[CONDENSE] Selected main content area: {main.tag if hasattr(main, 'tag') else 'root'}")
        
        # Clean up unwanted elements
        removed_count = 0
        for sel in ("script", "style", "noscript", "template", "svg", "iframe"):
            elements = main.css(sel)
            removed_count += len(elements)
            for n in elements:
                n.decompose()
        print(f"[CONDENSE] Removed {removed_count} unwanted elements")
        
        t_anchors_start = time.perf_counter()
        anchors = self._anchors_from(main, base_url)
        t_anchors = (time.perf_counter() - t_anchors_start) * 1000
        print(f"[CONDENSE] Extracted {len(anchors)} anchors in {t_anchors:.1f}ms")
        
        t_text_start = time.perf_counter()
        text = self._take_text(main, limit_chars=limit_text_chars)
        
        # Add meta descriptions (from v2)
        meta = self._meta_descriptions(doc)
        if meta:
            text = f"{meta}\n{text}"
        
        t_text = (time.perf_counter() - t_text_start) * 1000
        print(f"[CONDENSE] Extracted text ({len(text)} chars) in {t_text:.1f}ms")
        
        total_time = (time.perf_counter() - t_start) * 1000
        print(f"[CONDENSE] Condensation completed in {total_time:.1f}ms")
        
        return {"text": text, "anchors": anchors, "html_chars": len(html), "text_chars": len(text)}

    async def condense_url(self, url: str, use_cache=True, limit_text_chars=16000) -> Dict[str, Any]:
        print(f"[CONDENSE_URL] Processing URL: {url}")
        overall_start = time.perf_counter()
        
        html, cached, t_fetch = await self.fetch_html(url, use_cache=use_cache)
        t0 = time.perf_counter()
        result = self.condense_html(html, url, limit_text_chars=limit_text_chars)
        t_condense = (time.perf_counter() - t0) * 1000
        
        total_time = (time.perf_counter() - overall_start) * 1000
        result["timing"] = {
            "t_fetch_ms": round(t_fetch,1),
            "t_condense_ms": round(t_condense,1),
            "t_total_ms": round(t_fetch + t_condense,1),
            "from_cache": cached
        }
        result["url"] = url
        
        print(f"[CONDENSE_URL] Completed in {total_time:.1f}ms (fetch: {t_fetch:.1f}ms, condense: {t_condense:.1f}ms)")
        return result

# -------------------- LLM Extractor --------------------

class LLMExtractor:
    def __init__(self, model_listing="gpt-5-mini", model_detail="gpt-5-mini"):
        self.client = OpenAI()
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
        print(f"[ORCHESTRATOR] Getting listing bundle for: {museum_url}")
        t_start = time.perf_counter()
        
        base_bundle = await self.c.condense_url(museum_url, use_cache=self.cache)
        bundles = [base_bundle]
        print(f"[ORCHESTRATOR] Base bundle: {len(base_bundle['anchors'])} anchors, {len(base_bundle['text'])} chars")
        
        if self.follow_pagination:
            pagers = [a for a in base_bundle["anchors"] if a.get("pager")]
            print(f"[ORCHESTRATOR] Found {len(pagers)} pagination links")
            
            # follow up to 3 pagination links to avoid explosion
            for i, a in enumerate(pagers[:3]):
                print(f"[ORCHESTRATOR] Following pagination link {i+1}: {a['href']}")
                try:
                    b = await self.c.condense_url(a["href"], use_cache=self.cache)
                    bundles.append(b)
                    print(f"[ORCHESTRATOR] Pagination {i+1} success: {len(b['anchors'])} anchors, {len(b['text'])} chars")
                except Exception as e:
                    print(f"[ORCHESTRATOR] Pagination {i+1} failed: {e}")
                    continue
        
        # merge anchors + take longest text
        anchors = []
        text_chunks = []
        for i, b in enumerate(bundles):
            anchors.extend(b["anchors"])
            text_chunks.append(b["text"])
            print(f"[ORCHESTRATOR] Bundle {i}: {len(b['anchors'])} anchors, {len(b['text'])} chars")
        
        merged_text = "\n".join(text_chunks)[:16000]
        merged = {
            "text": merged_text,
            "anchors": anchors,
            "timing": base_bundle["timing"],
            "url": museum_url
        }
        
        elapsed = (time.perf_counter() - t_start) * 1000
        print(f"[ORCHESTRATOR] Listing bundle complete in {elapsed:.1f}ms: {len(anchors)} total anchors, {len(merged_text)} chars")
        return merged

    async def _fetch_detail_and_extract(self, museum_name: str, href: str, timings: Dict[str, Any]) -> Optional[Exhibition]:
        print(f"[DETAIL] Starting detail extraction for: {href}")
        async with self.semaphore:
            t0 = time.perf_counter()
            try:
                bundle = await self.c.condense_url(href, use_cache=self.cache)
                print(f"[DETAIL] Fetch successful: {bundle['html_chars']} html chars -> {bundle['text_chars']} text chars")
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                print(f"[DETAIL] Fetch failed after {elapsed:.1f}ms: {e}")
                timings[href] = {"status": "fetch_error", "error": str(e)}
                return None
                
            t_fetch_total = bundle["timing"]["t_total_ms"]
            
            # KEY SPEEDUP: Run LLM in thread pool for parallelism (from v2)
            t1 = time.perf_counter()
            try:
                rec = await asyncio.to_thread(
                    self.llm.extract_detail, 
                    museum_name, 
                    bundle["text"], 
                    href
                )
                t_llm = (time.perf_counter() - t1) * 1000
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                print(f"[DETAIL] LLM extraction failed after {elapsed:.1f}ms: {e}")
                timings[href] = {"status": "llm_error", "error": str(e)}
                return None
            
            total_elapsed = (time.perf_counter() - t0) * 1000
            print(f"[DETAIL] Detail extraction completed in {total_elapsed:.1f}ms (fetch: {t_fetch_total:.1f}ms, llm: {t_llm:.1f}ms)")
            
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
        print(f"\n[MUSEUM] ========== Starting processing for {museum_name} ==========\n")
        overall_start = time.perf_counter()
        
        print(f"[MUSEUM] Step 1: Getting listing bundle")
        listing_bundle = await self._get_listing_bundle(listing_url)
        t_listing = listing_bundle["timing"]
        print(f"[MUSEUM] Listing bundle obtained in {t_listing['t_total_ms']}ms")

        # LLM: pick exhibitions from anchors
        print(f"[MUSEUM] Step 2: LLM extraction of exhibition list")
        t0 = time.perf_counter()
        items = self.llm.extract_listing(museum_name, listing_bundle["text"], listing_bundle["anchors"])
        t_llm_listing = (time.perf_counter() - t0) * 1000
        print(f"[MUSEUM] LLM listing extraction completed in {t_llm_listing:.1f}ms")

        # Dedup by href - DON'T filter aggressively (keep v1 approach)
        print(f"[MUSEUM] Step 3: Deduplicating by href")
        seen = set(); todo = []
        for it in items:
            href = it.href
            if href in seen: 
                print(f"[MUSEUM] Duplicate href skipped: {href}")
                continue
            seen.add(href); todo.append(it)
        print(f"[MUSEUM] After dedup: {len(todo)} unique exhibitions to process")

        # Fetch details concurrently with parallel LLM
        print(f"[MUSEUM] Step 4: Fetching details concurrently (max {self.semaphore._value} concurrent)")
        per_page_timings: Dict[str, Any] = {}
        coros = [self._fetch_detail_and_extract(museum_name, it.href, per_page_timings) for it in todo]
        
        t_details_start = time.perf_counter()
        results = await asyncio.gather(*coros)
        t_details = (time.perf_counter() - t_details_start) * 1000
        print(f"[MUSEUM] All detail fetching completed in {t_details:.1f}ms")

        # Dedup by normalized title & fill museum
        print(f"[MUSEUM] Step 5: Final deduplication by normalized title")
        uniq, titles_seen = [], set()
        skipped_count = 0
        for i, ex in enumerate(results):
            if not ex or not ex.title: 
                skipped_count += 1
                continue
            ex.museum = museum_name
            key = normalize_title_key(ex.title)
            if key in titles_seen: 
                print(f"[MUSEUM] Duplicate title skipped: '{ex.title}'")
                skipped_count += 1
                continue
            titles_seen.add(key); uniq.append(ex)
            print(f"[MUSEUM] Added exhibition {len(uniq)}: '{ex.title}'")
        
        if skipped_count > 0:
            print(f"[MUSEUM] Skipped {skipped_count} exhibitions (duplicates or empty)")

        overall_ms = (time.perf_counter() - overall_start) * 1000
        
        # Count successful vs failed detail fetches
        scraped_count = len([x for x in results if x])
        failed_count = len(todo) - scraped_count
        
        print(f"\n[MUSEUM] ========== Summary for {museum_name} ==========\n")
        print(f"[MUSEUM] Total processing time: {overall_ms:.1f}ms")
        print(f"[MUSEUM] Listing fetch: {t_listing['t_total_ms']}ms")
        print(f"[MUSEUM] Listing LLM: {t_llm_listing:.1f}ms")
        print(f"[MUSEUM] Detail fetching: {t_details:.1f}ms")
        print(f"[MUSEUM] Exhibition counts:")
        print(f"[MUSEUM]   - Candidates found: {len(todo)}")
        print(f"[MUSEUM]   - Successfully scraped: {scraped_count}")
        print(f"[MUSEUM]   - Failed to scrape: {failed_count}")
        print(f"[MUSEUM]   - Final unique: {len(uniq)}")
        print(f"[MUSEUM] ================================================\n")
        
        summary = {
            "museum": museum_name,
            "listing_url": listing_url,
            "counts": {
                "todo": len(todo),
                "scraped": scraped_count,
                "failed": failed_count,
                "unique": len(uniq)
            },
            "timing_ms": {
                "listing_fetch": t_listing["t_total_ms"],
                "listing_llm": round(t_llm_listing,1),
                "details_fetch": round(t_details,1),
                "overall": round(overall_ms,1)
            },
            "per_page": per_page_timings
        }
        return {"summary": summary, "exhibitions": [asdict(x) for x in uniq]}

# -------------------- CLI / Example --------------------

async def main():
    print("[MAIN] ========================================")
    print("[MAIN] Exhibition Pipeline Starting")
    print("[MAIN] ========================================\n")
    
    main_start = time.perf_counter()
    
    museums = [
        {"name": "National Gallery of Ireland", "url": "https://www.nationalgallery.ie/art-and-artists/exhibitions"},
        # {"name": "The Met", "url": "https://www.metmuseum.org/exhibitions"},
        # {"name": "Fine Arts Museums of San Francisco", "url": "https://www.famsf.org/whats-on"},
    ]
    
    print(f"[MAIN] Configuration:")
    print(f"[MAIN]   - Museums to process: {len(museums)}")
    for i, m in enumerate(museums, 1):
        print(f"[MAIN]   - Museum {i}: {m['name']}")
    print()

    print(f"[MAIN] Initializing components...")
    condenser = PageCondenser()
    llm = LLMExtractor(model_listing="gpt-5-mini", model_detail="gpt-5-mini")
    orch = ExhibitionsOrchestrator(condenser, llm, follow_pagination=True, detail_concurrency=12, cache=True)
    print(f"[MAIN] Components initialized (concurrency: 12, cache: enabled, pagination: enabled)\n")

    all_out = {"runs": [], "exhibitions": []}
    total_exhibitions = 0
    
    try:
        for i, m in enumerate(museums, 1):
            print(f"[MAIN] Processing museum {i}/{len(museums)}: {m['name']}")
            museum_start = time.perf_counter()
            
            try:
                result = await orch.run_for_museum(m["name"], m["url"])
                museum_time = (time.perf_counter() - museum_start) * 1000
                
                # logging
                s = result["summary"]
                exhibitions_found = len(result["exhibitions"])
                total_exhibitions += exhibitions_found
                
                print(f"[MAIN] Museum {i} completed in {museum_time:.1f}ms")
                print(f"[MAIN] Timing breakdown: Listing {s['timing_ms']['listing_fetch']}ms | LLM {s['timing_ms']['listing_llm']}ms | Details {s['timing_ms']['details_fetch']}ms")
                print(f"[MAIN] Results: {s['counts']['todo']} candidates → {s['counts']['scraped']} scraped → {s['counts']['unique']} unique")
                
                # Show slowest pages for debugging
                if s["per_page"]:
                    print(f"[MAIN] Slowest detail pages:")
                    slow = sorted(s["per_page"].items(), key=lambda kv: (kv[1].get("t_fetch_ms",0)+kv[1].get("t_llm_ms",0)), reverse=True)[:3]
                    for url, t in slow:
                        if t.get("status")=="ok":
                            total_time = t.get('t_fetch_ms', 0) + t.get('t_llm_ms', 0)
                            cache_status = "(cached)" if t.get('from_cache') else "(fresh)"
                            print(f"[MAIN]   • {total_time:.1f}ms {cache_status}: {url[:80]}...")
                        elif t.get("status") == "fetch_error":
                            print(f"[MAIN]   • FAILED: {url[:80]}... - {t.get('error', 'Unknown error')}")
                
                all_out["runs"].append(s)
                all_out["exhibitions"].extend(result["exhibitions"])
                
            except Exception as e:
                museum_time = (time.perf_counter() - museum_start) * 1000
                print(f"[MAIN] ERROR: Museum {i} failed after {museum_time:.1f}ms: {e}")
                print(f"[MAIN] Continuing with next museum...")
                continue
            
            print(f"[MAIN] Museum {i} summary: {exhibitions_found} exhibitions added\n")
            
    except KeyboardInterrupt:
        print(f"[MAIN] Interrupted by user")
        raise
    except Exception as e:
        print(f"[MAIN] Unexpected error: {e}")
        raise
    finally:
        print(f"[MAIN] Closing HTTP client...")
        await condenser.close()
        print(f"[MAIN] HTTP client closed")

    # Save artifacts
    main_elapsed = (time.perf_counter() - main_start) * 1000
    
    print(f"[MAIN] ========================================")
    print(f"[MAIN] Pipeline Complete - Saving Results")
    print(f"[MAIN] ========================================\n")
    
    print(f"[MAIN] Final Summary:")
    print(f"[MAIN]   - Total runtime: {main_elapsed:.1f}ms ({main_elapsed/1000:.1f}s)")
    print(f"[MAIN]   - Museums processed: {len(all_out['runs'])}/{len(museums)}")
    print(f"[MAIN]   - Total exhibitions found: {len(all_out['exhibitions'])}")
    print(f"[MAIN]   - Average time per museum: {main_elapsed/max(len(all_out['runs']), 1):.1f}ms")
    print()
    
    print(f"[MAIN] Saving output files...")
    save_start = time.perf_counter()
    
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    
    exhibitions_file = out_dir / "exhibitions.json"
    runs_file = out_dir / "runs_summary.json"
    
    try:
        exhibitions_file.write_text(json.dumps(all_out["exhibitions"], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[MAIN] ✓ Saved exhibitions: {exhibitions_file} ({len(all_out['exhibitions'])} records)")
        
        runs_file.write_text(json.dumps(all_out["runs"], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[MAIN] ✓ Saved run summary: {runs_file}")
        
        save_elapsed = (time.perf_counter() - save_start) * 1000
        print(f"[MAIN] File saving completed in {save_elapsed:.1f}ms")
        
    except Exception as e:
        print(f"[MAIN] ERROR: Failed to save files: {e}")
        raise
    
    print(f"\n[MAIN] ========================================")
    print(f"[MAIN] Exhibition Pipeline Finished Successfully")
    print(f"[MAIN] ========================================")

if __name__ == "__main__":
    asyncio.run(main())