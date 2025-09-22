# exhibitions_ultrafast.py
import asyncio, json, re, unicodedata, logging, time
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Tuple
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from browser_use import Agent, ChatOpenAI, Tools, Browser
from browser_use.agent.views import ActionResult

load_dotenv()

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("exhibitions-ultrafast")

# ---------------- Normalisers ----------------
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def normalize_title_key(title: Optional[str]) -> str:
    if not title: return ""
    t = strip_accents(title).casefold()
    t = re.sub(r"[^\w\s-]", "", t)
    return normalize_spaces(t)

def canonical_museum(name: Optional[str]) -> Optional[str]:
    if not name: return None
    nm = normalize_spaces(name).casefold()
    if "national gallery of ireland" in nm or "national gallery" in nm:
        return "National Gallery of Ireland"
    return normalize_spaces(name)

def normalize_url(u: Optional[str]) -> Optional[str]:
    if not u: return None
    u = u.strip()
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u

def normalize_date_range_fields(start_date: Optional[str], end_date: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    # Convert "1–31 January 2026" -> ("1 January 2026", "31 January 2026")
    if start_date and not end_date:
        m = re.match(r"^\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", start_date)
        if m:
            d1, d2, mon, yr = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
            return (f"{d1} {mon} {yr}", f"{d2} {mon} {yr}")
    return (start_date, end_date)

def clean_other_artists(names: Optional[List[str]]) -> List[str]:
    if not names: return []
    out = []
    for n in names:
        t = normalize_spaces(n or "")
        if not t: continue
        if re.search(r"\b(prize|portrait|exhibition|gallery)\b", t, re.I):  # filter non-names
            continue
        t = re.sub(r"\([^)]*\)", "", t).strip()  # drop (1757–1827)
        if t: out.append(t)
    # dedup
    seen, uniq = set(), []
    for t in out:
        k = normalize_title_key(t)
        if k not in seen:
            seen.add(k); uniq.append(t)
    return uniq

# ---------------- Data models ----------------
class ExhibitionData(BaseModel):
    title: str = Field(...)
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

class LinkItem(BaseModel):
    title: str
    href: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class TodoList(BaseModel):
    items: List[LinkItem]

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

# ---------------- Scraper ----------------
MODEL = "gpt-5-mini"   # fast; bump to "gpt-4o" if you need more fidelity

class UltraFastExhibitionScraper:
    def __init__(self, llm_model=MODEL):
        self.llm = ChatOpenAI(model=llm_model)
        self.exhibitions: List[Exhibition] = []
        self.tools = Tools()

        # todo queue + timings
        self.todo: List[LinkItem] = []
        self.todo_i: int = 0
        self.detail_start_ts: Dict[str, float] = {}
        self.detail_ms: Dict[str, float] = {}
        self.phase1_ms: float = 0.0

        self._setup_tools()

    # ---------- Custom tools ----------
    def _setup_tools(self):
        @self.tools.action(
            description="Save or update a single exhibition (validated & deduped).",
            param_model=ExhibitionData
        )
        def save_exhibition_data(params: ExhibitionData) -> ActionResult:
            if not params.title or not params.title.strip():
                return ActionResult(extracted_content="Skipped empty title", long_term_memory="skip:empty_title")

            title = normalize_spaces(params.title)
            # Prize heuristic: never set main_artist for prize shows
            main_artist = params.main_artist
            if re.search(r"\bprize\b", title, re.I):
                main_artist = None

            other_artists = clean_other_artists(params.other_artists or [])
            s, e = normalize_date_range_fields(params.start_date, params.end_date)
            museum = canonical_museum(params.museum) or "National Gallery of Ireland"
            url = normalize_url(params.url)

            key = normalize_title_key(title)
            idx = next((i for i, ex in enumerate(self.exhibitions) if normalize_title_key(ex.title) == key), None)

            if idx is not None:
                cur = self.exhibitions[idx]
                upd = Exhibition(
                    title=title or cur.title,
                    main_artist=main_artist or cur.main_artist,
                    other_artists=(other_artists or cur.other_artists),
                    start_date=s or cur.start_date,
                    end_date=e or cur.end_date,
                    museum=museum or cur.museum,
                    details=(params.details if (params.details and len(params.details or "") > len(cur.details or "")) else cur.details),
                    url=url or cur.url
                )
                self.exhibitions[idx] = upd
                return ActionResult(extracted_content=f"Updated: {title}", long_term_memory=f"updated:{title}")
            else:
                self.exhibitions.append(Exhibition(
                    title=title, main_artist=main_artist, other_artists=other_artists,
                    start_date=s, end_date=e, museum=museum, details=params.details, url=url
                ))
                return ActionResult(extracted_content=f"Saved: {title}", long_term_memory=f"saved:{title}")

        @self.tools.action(
            description="Set the todo list from listing page extraction (called once).",
            param_model=TodoList
        )
        def set_todo_list(params: TodoList) -> ActionResult:
            t0 = getattr(self, "_phase1_t0", None)
            self.todo = params.items
            self.todo_i = 0
            # timing: Phase 1 duration
            if t0 is not None:
                self.phase1_ms = (time.time() - t0) * 1000.0
            return ActionResult(
                extracted_content=f"Todo initialised with {len(self.todo)} items",
                long_term_memory=f"todo_init:{len(self.todo)}"
            )

        @self.tools.action(
            description="Return the next todo item as JSON, or 'NONE' if empty."
        )
        def pop_next_todo() -> ActionResult:
            if self.todo_i >= len(self.todo):
                return ActionResult(extracted_content="NONE", long_term_memory="todo_empty")
            item = self.todo[self.todo_i]
            self.todo_i += 1
            self.detail_start_ts[item.title] = time.time()
            payload = json.dumps(item.dict(), ensure_ascii=False)
            return ActionResult(extracted_content=payload, long_term_memory=f"todo_pop:{item.href}")

        @self.tools.action(
            description="Mark current todo item complete and record timing.",
            param_model=LinkItem
        )
        def mark_todo_complete(params: LinkItem) -> ActionResult:
            t0 = self.detail_start_ts.get(params.title)
            if t0:
                elapsed_ms = (time.time() - t0) * 1000.0
                self.detail_ms[params.title] = elapsed_ms
            remaining = max(0, len(self.todo) - self.todo_i)
            return ActionResult(
                extracted_content=f"Completed: {params.title} ({remaining} left)",
                long_term_memory=f"todo_done:{params.title}"
            )

    # ---------- Core scrape ----------
    async def scrape_museum_exhibitions(self, museum_urls: List[str]) -> List[Exhibition]:
        for url in museum_urls:
            log.info(f"🚀 Ultra-fast scraping: {url}")
            try:
                agent = Agent(
                    task=f"""
You are collecting exhibitions from {url}. Use DOM-only tools. Be fast and decisive.

Use the tool **extract_structured_data** exactly as follows:

PHASE 1 — BULK LISTING EXTRACTION (ONE CALL)
- Ensure you are on the listing page: {url}
- Call extract_structured_data ONCE with:
  - query:
    "List ALL exhibition cards/rows (current & upcoming). For each item output:
     - title
     - absolute href
     - visible date text (e.g., '2 August 2025 - 25 January 2026' OR '1–31 January 2026')
     Return as a compact JSON array of objects: {{title, href, date}}.
     Do NOT include anything else."
  - extract_links=True
- If the tool responds with content truncated, do NOT call it again; proceed with what you have.
- Transform that JSON into items: title, href, start_date (put the raw 'date' string here), end_date empty for now.
- Call set_todo_list ONCE passing the full array.
- Also call save_exhibition_data for each listing item (title, url=href, start_date as the raw date string, museum='National Gallery of Ireland').

PHASE 2 — DETAIL ENRICHMENT (LOOP)
Repeat until pop_next_todo returns "NONE":
  1) Call pop_next_todo -> parse JSON {{title, href, start_date, end_date}}.
  2) go_to_url(href)  # DO NOT GUESS SLUGS. No retries. No scrolling.
  3) Call extract_structured_data ONCE with:
     - query:
       "From this exhibition page, extract:
        - main artist name (names only; strip birth/death years)
        - other artist names (list; names only)
        - improved date range (start and end shown on page; if '1–31 January 2026' provide it as-is)
        - a short summary paragraph (first concise description)
        Return JSON: {{main_artist, other_artists[], start_date, end_date, details}}."
     - extract_links=False
  4) Call save_exhibition_data using title from the todo & the extracted fields (keep url as the current page href).
  5) Call mark_todo_complete with the exact todo item fields.

STRICT SPEED RULES
- Never use vision. Never scroll unless absolutely necessary.
- Never call extract_structured_data more than once per page.
- No retries on 404 or errors; just mark complete and continue.
- Keep steps minimal and focused.

DATA HYGIENE
- Never save blank titles.
- If title contains 'Prize', main_artist must be empty.
- Keep museum = "National Gallery of Ireland".
- Names: strip '(1757–1827)' etc.

Finish when todo is empty.
                    """,
                    llm=self.llm,
                    tools=self.tools,
                    browser=Browser(
                        headless=True,                 # speed
                        enable_default_extensions=False
                    ),
                    use_vision=False                  # DOM only
                )
                # mark phase1 start for timing
                self._phase1_t0 = time.time()
                await agent.run(max_steps=26)  # enough for ~8–10 items. Increase if needed.

            except Exception as e:
                log.error(f"Error scraping {url}: {e}")
                continue

        # Final dedup by normalized title
        seen, uniq = set(), []
        for ex in self.exhibitions:
            if not ex.title or not ex.title.strip(): continue
            k = normalize_title_key(ex.title)
            if k in seen: continue
            seen.add(k); uniq.append(ex)
        self.exhibitions = uniq
        return self.exhibitions

    # ---------- Output helpers ----------
    def save_to_json(self, path: str = "exhibitions_ultrafast.json"):
        data = [asdict(ex) for ex in self.exhibitions]
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"💾 Saved {len(self.exhibitions)} exhibitions to {path}")

    def print_results(self):
        print(f"\n📋 Found {len(self.exhibitions)} exhibitions")
        print("="*80)
        for i, ex in enumerate(self.exhibitions, 1):
            print(f"{i}. {ex.title}")
            if ex.main_artist: print(f"   Main: {ex.main_artist}")
            if ex.other_artists: print(f"   Others: {', '.join(ex.other_artists)}")
            if ex.start_date or ex.end_date:
                print(f"   Dates: {ex.start_date or 'TBD'} - {ex.end_date or 'TBD'}")
            if ex.museum: print(f"   Museum: {ex.museum}")
            if ex.url: print(f"   URL: {ex.url}")
            if ex.details:
                print(f"   Details: {ex.details[:120]}{'...' if len(ex.details)>120 else ''}")
            print()

    def print_timing_report(self, started_at: float):
        total_ms = (time.time() - started_at) * 1000.0
        print("\n⏱️  Timing report")
        print("="*80)
        print(f"Phase 1 (listing)      : {self.phase1_ms:7.1f} ms")
        # Sort per-page times desc
        if self.detail_ms:
            print("Detail pages:")
            for title, ms in sorted(self.detail_ms.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {title[:50]:50s} : {ms:7.1f} ms")
            avg = sum(self.detail_ms.values()) / len(self.detail_ms)
            print(f"Avg detail page        : {avg:7.1f} ms ({len(self.detail_ms)} pages)")
        else:
            print("Detail pages: none visited or timed.")
        print(f"TOTAL                   : {total_ms:7.1f} ms")

# ---------------- Ground truth comparison ----------------
def normalize_for_map(e: Dict) -> Dict:
    return {
        "title": normalize_spaces(e.get("title") or ""),
        "main_artist": normalize_spaces(e.get("main_artist") or "") or None,
        "other_artists": [normalize_spaces(x) for x in (e.get("other_artists") or [])],
        "start_date": normalize_spaces(e.get("start_date") or "") or None,
        "end_date": normalize_spaces(e.get("end_date") or "") or None,
        "museum": canonical_museum(e.get("museum")) or None,
        "url": normalize_url(e.get("url") or "") or None,
        "details": e.get("details")
    }

def _map_by_title(rows: List[Dict]) -> Dict[str, Dict]:
    out = {}
    for r in rows:
        k = normalize_title_key(r.get("title",""))
        if k: out[k] = r
    return out

def compare_with_groundtruth(scraped_path: str, truth_path: str) -> None:
    scraped = json.loads(Path(scraped_path).read_text(encoding="utf-8"))
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    smap, tmap = _map_by_title(scraped), _map_by_title(truth)

    sk, tk = set(smap.keys()), set(tmap.keys())
    missing, extra, matched = sorted(tk-sk), sorted(sk-tk), sorted(sk & tk)

    print("\n=== 📊 Ground Truth Comparison ===")
    print(f"Ground truth: {len(tk)} | Scraped: {len(sk)}")
    print(f"Missing: {len(missing)} | Extra: {len(extra)} | Matched: {len(matched)}\n")

    if missing:
        print("❌ Missing titles:")
        for k in missing: print("   -", tmap[k]["title"])
        print()
    if extra:
        print("➕ Extra titles:")
        for k in extra: print("   -", smap[k]["title"])
        print()

    def completeness(scr: Dict, tru: Dict) -> float:
        fields = ["main_artist","other_artists","start_date","end_date","museum","url"]
        ok = 0; ttl = 0
        for f in fields:
            tv = tru.get(f)
            if tv is None: continue
            ttl += 1
            sv = scr.get(f)
            if f == "other_artists":
                if set(sv or []) == set(tv or []): ok += 1
            else:
                if (sv or None) == (tv or None): ok += 1
        return ok/ttl if ttl else 1.0

    scores = []
    for k in matched:
        a, b = normalize_for_map(smap[k]), normalize_for_map(tmap[k])
        scores.append(completeness(a,b))

    if scores:
        print(f"📈 Average completeness on matched: {sum(scores)/len(scores):.1%}")

# ---------------- Main ----------------
async def main():
    started_at = time.time()
    urls = ["https://www.nationalgallery.ie/art-and-artists/exhibitions"]
    scraper = UltraFastExhibitionScraper()
    await scraper.scrape_museum_exhibitions(urls)

    scraper.print_results()
    out = "exhibitions_ultrafast.json"
    scraper.save_to_json(out)

    # choose the groundtruth filename you actually have
    gt_candidates = ["ngi_exhibitions_groundruth.json", "ngi_exhibitions_groundtruth.json"]
    gt = next((p for p in gt_candidates if Path(p).exists()), None)
    if gt:
        compare_with_groundtruth(out, gt)
    else:
        print("\n⚠️  Ground truth file not found; skipping comparison.")

    scraper.print_timing_report(started_at)

if __name__ == "__main__":
    asyncio.run(main())
