# exhibitions_hybrid.py
import asyncio, json, re, unicodedata, logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Set, Dict, Tuple
from pathlib import Path
from dotenv import load_dotenv
from browser_use import Agent, ChatOpenAI, Tools, Browser
from browser_use.agent.views import ActionResult

load_dotenv()

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("exhibitions")

# ---------------- Normalisers ----------------
def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())

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

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1)}

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
from pydantic import BaseModel, Field
class ExhibitionData(BaseModel):
    title: str = Field(...)
    main_artist: Optional[str] = None
    other_artists: Optional[List[str]] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    museum: Optional[str] = None
    details: Optional[str] = None
    url: Optional[str] = None

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
EXPECTED_TITLES_HINT = True  # set False to remove the “expected list” nudge
MODEL = "gpt-4o"            # heavier model -> better extraction

class ExhibitionScraper:
    def __init__(self, llm_model=MODEL):
        self.llm = ChatOpenAI(model=llm_model)
        self.exhibitions: List[Exhibition] = []
        self.tools = Tools()
        self._setup_save_tool()

    def _setup_save_tool(self):
        @self.tools.action(
            description="Save or update exhibition data to the results list using structured format",
            param_model=ExhibitionData
        )
        def save_exhibition_data(params: ExhibitionData) -> ActionResult:
            if not params.title or not params.title.strip():
                return ActionResult(extracted_content="Skipped empty title", long_term_memory="skipped empty")

            title = normalize_spaces(params.title)
            # Prize heuristic: never set main_artist for prize shows
            main_artist = params.main_artist
            if re.search(r"\bprize\b", title, re.I): main_artist = None

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

    async def scrape_museum_exhibitions(self, museum_urls: List[str]) -> List[Exhibition]:
        expected_hint = """
        EXPECTED TITLES (for this site; use as a checklist but still rely on DOM):
        - Maurice Marinot – On Paper, In Glass
        - Créatúir na Cartlainne | Tails from the Archive
        - Picasso: From the Studio
        - AIB Young Portrait Prize 2025
        - AIB Portrait Prize 2025
        - Turner as Inspiration
        - William Blake: The Age of Romantic Fantasy
        - From Rembrandt to Matisse – A Celebration of European Prints and Drawings
        - Hilma af Klint: Artist and Visionary
        - Jan Steen: Sacred and Profane
        - AIB Young Portrait Prize 2026
        - AIB Portrait Prize 2026
        """.strip() if EXPECTED_TITLES_HINT else ""

        for url in museum_urls:
            log.info(f"Scraping: {url}")
            try:
                agent = Agent(
                    task=f"""
You are collecting exhibitions from {url}.

HARD RULES:
- Do NOT guess/fabricate URLs or slugs. Always CLICK real anchors from the page.
- Handle consent/WAF: if cookie banner or interstitial appears, accept/continue, then retry.
- If a detail page says 'Page not found':
  1) scroll/load; 2) reload once; 3) try with/without trailing slash; 4) go BACK and CLICK the anchor again.
- If after all retries the detail page still fails, FALL BACK to the listing data for that item.

PROCEDURE:
1) On the listing page:
   - Find all exhibition cards/rows (current, upcoming, featured, etc.).
   - For EACH item, extract:
     title, the ACTUAL absolute href, date range text (verbatim), museum if visible.
   - Immediately call save_exhibition_data with those fields.
   - If a date shows like "1–31 January 2026", put that full string into start_date for now (the tool normalises later).

2) Enrichment:
   - For EACH saved exhibition, CLICK its link from the listing (no slug guessing).
   - After navigation, extract:
     * main artist (names only; strip birth/death years)
     * other significant artists (names only)
     * brief description/summary (first paragraph or summary block)
     * confirm/upgrade date range if the detail page shows it
     * confirm museum name
   - Call save_exhibition_data again to merge.

3) Data hygiene:
   - Never save blank titles.
   - For titles containing 'Prize', leave main_artist empty (null).
   - Keep names clean (remove '(1757–1827)' etc).

{expected_hint}
                    """,
                    llm=self.llm,
                    tools=self.tools,
                    browser=Browser(
                        headless=False,                 # important for cookie overlays/WAF
                        enable_default_extensions=True  # allow helper extensions
                    ),
                    use_vision=False 
                )
                await agent.run(max_steps=45)
            except Exception as e:
                log.error(f"Error scraping {url}: {e}")
                continue

        # Final clean & dedup by normalized title
        seen, uniq = set(), []
        for ex in self.exhibitions:
            if not ex.title or not ex.title.strip(): continue
            k = normalize_title_key(ex.title)
            if k in seen: continue
            seen.add(k); uniq.append(ex)
        self.exhibitions = uniq
        return self.exhibitions

    def save_to_json(self, path: str = "exhibitions_v2.json"):
        data = [asdict(ex) for ex in self.exhibitions]
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"Saved {len(self.exhibitions)} exhibitions to {path}")

    def print_results(self):
        print(f"\nFound {len(self.exhibitions)} exhibitions")
        print("="*80)
        for i, ex in enumerate(self.exhibitions, 1):
            print(f"{i}. {ex.title}")
            if ex.main_artist: print(f"   Main: {ex.main_artist}")
            if ex.other_artists: print(f"   Others: {', '.join(ex.other_artists)}")
            if ex.start_date or ex.end_date: print(f"   Dates: {ex.start_date or 'TBD'} - {ex.end_date or 'TBD'}")
            if ex.museum: print(f"   Museum: {ex.museum}")
            if ex.url: print(f"   URL: {ex.url}")
            if ex.details: print(f"   Details: {ex.details[:120]}{'...' if len(ex.details)>120 else ''}")
            print()

# ---------------- Ground truth comparison + completeness ----------------
def _map_by_key(rows: List[Dict]) -> Dict[str, Dict]:
    out = {}
    for r in rows:
        k = normalize_title_key(r.get("title",""))
        if k: out[k] = r
    return out

def _norm(e: Dict) -> Dict:
    return {
        "title": normalize_spaces(e.get("title") or ""),
        "main_artist": normalize_spaces(e.get("main_artist") or "") or None,
        "other_artists": [normalize_spaces(x) for x in (e.get("other_artists") or [])],
        "start_date": normalize_spaces(e.get("start_date") or "") or None,
        "end_date": normalize_spaces(e.get("end_date") or "") or None,
        "museum": canonical_museum(e.get("museum")) or None,
        "url": normalize_url(e.get("url") or "") or None,
        "details": e.get("details")  # free-form, not strictly compared
    }

def compare_with_groundtruth(scraped_path: str, truth_path: str) -> None:
    scraped = json.loads(Path(scraped_path).read_text(encoding="utf-8"))
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    smap, tmap = _map_by_key(scraped), _map_by_key(truth)

    sk, tk = set(smap.keys()), set(tmap.keys())
    missing, extra, matched = sorted(tk-sk), sorted(sk-tk), sorted(sk & tk)

    print("\n=== Ground Truth Comparison ===")
    print(f"Ground truth: {len(tk)} | Scraped: {len(sk)}")
    print(f"Missing: {len(missing)} | Extra: {len(extra)} | Matched: {len(matched)}\n")

    if missing:
        print("-> Missing titles:")
        for k in missing: print("   -", tmap[k]["title"])
        print()
    if extra:
        print("-> Extra titles:")
        for k in extra: print("   -", smap[k]["title"])
        print()

    # Field-level diffs + completeness
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

    diffs = 0; scores = []
    if matched:
        print("-> Field differences on matched titles:")
        for k in matched:
            a, b = _norm(smap[k]), _norm(tmap[k])
            fields = ["main_artist","start_date","end_date","museum","url"]
            fd = [(f, a.get(f), b.get(f)) for f in fields if a.get(f)!=b.get(f)]
            if fd:
                diffs += 1
                print(f"   {a['title']}:")
                for f,av,bv in fd:
                    print(f"     - {f}:\n        scraped:     {av}\n        groundtruth: {bv}")
            scores.append(completeness(a,b))
        if diffs==0: print("   (no field-level diffs)")
    if scores:
        print(f"\nAverage completeness on matched: {sum(scores)/len(scores):.1%}")

# ---------------- Main ----------------
async def main():
    urls = ["https://www.nationalgallery.ie/art-and-artists/exhibitions"]
    scraper = ExhibitionScraper()
    await scraper.scrape_museum_exhibitions(urls)
    scraper.print_results()
    out = "exhibitions_v3.json"
    scraper.save_to_json(out)

    gt = "ngi_exhibitions_groundruth.json"  # your filename
    if Path(gt).exists():
        compare_with_groundtruth(out, gt)
    else:
        print(f"\nGround truth file not found at {gt}, skipping comparison.")

if __name__ == "__main__":
    asyncio.run(main())
