import time
from typing import Dict, Any, Optional, List
import asyncio
from dataclasses import asdict

from backend.scraper.condenser import PageCondenser
from backend.scraper.extractor import LLMExtractor
from backend.scraper.models import Exhibition
from backend.scraper.utils import normalize_title_key

class ExhibitionsOrchestrator:
    def __init__(self, condenser: PageCondenser, llm: LLMExtractor,
                 follow_pagination=True, detail_concurrency=10, cache=True,
                 detail_mode: str = "full", light_cap: int = 10):
        self.c = condenser
        self.llm = llm
        self.follow_pagination = follow_pagination
        self.semaphore = asyncio.Semaphore(detail_concurrency)
        self.cache = cache
        self.detail_mode = detail_mode  # "full" | "light" | "off"
        self.light_cap = light_cap

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
            
            # KEY SPEEDUP: Run LLM in thread pool for parallelism
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
            return Exhibition(
                title=rec.title,
                main_artist=rec.main_artist,
                other_artists=rec.other_artists,
                start_date=rec.start_date,
                end_date=rec.end_date,
                museum_name=museum_name,
                details=rec.details,
                url=rec.url,
            )

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
        items = await asyncio.to_thread(
            self.llm.extract_listing,
            museum_name,
            listing_bundle["text"],
            listing_bundle["anchors"],
        )
        t_llm_listing = (time.perf_counter() - t0) * 1000
        print(f"[MUSEUM] LLM listing extraction completed in {t_llm_listing:.1f}ms")

        # Dedup by href first
        print(f"[MUSEUM] Step 3: Deduplicating by href")
        seen = set()
        dedup_items = []
        for it in items:
            href = it.href
            if href in seen:
                print(f"[MUSEUM] Duplicate href skipped: {href}")
                continue
            seen.add(href)
            dedup_items.append(it)
        print(f"[MUSEUM] After dedup: {len(dedup_items)} unique listings")

        # Decide which items need details based on detail_mode
        print(f"[MUSEUM] Step 4: Selecting items for detail fetch (mode={self.detail_mode})")
        if self.detail_mode == "off":
            todo = []
        elif self.detail_mode == "light":
            candidates = [it for it in dedup_items if not it.date_text or len(it.title.split()) <= 2]
            todo = candidates[: self.light_cap]
        else:
            todo = dedup_items
        print(f"[MUSEUM] Detail fetch candidates: {len(todo)} (max concurrency {self.semaphore._value})")

        # Build base records from listing for all deduplicated items
        base_records: List[Exhibition] = []
        for it in dedup_items:
            base_records.append(Exhibition(
                title=it.title,
                url=it.href,
                start_date=it.date_text,
                end_date=None,
                details=None
            ))

        # Only fetch/LLM for selected todo
        print(f"[MUSEUM] Step 5: Fetching details for selected items")
        per_page_timings: Dict[str, Any] = {}
        detail_results: List[Exhibition] = []
        t_details = 0.0
        if self.detail_mode != "off" and todo:
            coros = [self._fetch_detail_and_extract(museum_name, it.href, per_page_timings) for it in todo]
            t_details_start = time.perf_counter()
            fetched = await asyncio.gather(*coros, return_exceptions=True)
            t_details = (time.perf_counter() - t_details_start) * 1000
            for r in fetched:
                if isinstance(r, Exception):
                    print(f"[MUSEUM] Detail task error: {r}")
                elif isinstance(r, Exhibition):
                    detail_results.append(r)
        print(f"[MUSEUM] Detail fetching completed in {t_details:.1f}ms for {len(detail_results)} items")

        # Merge detail fields back over base, preferring detail values
        by_url: Dict[str, Exhibition] = {ex.url: ex for ex in base_records}
        for ex in detail_results:
            base = by_url.get(ex.url)
            if base:
                if ex.main_artist:
                    base.main_artist = ex.main_artist
                if ex.other_artists:
                    base.other_artists = ex.other_artists
                if ex.start_date:
                    base.start_date = ex.start_date
                if ex.end_date:
                    base.end_date = ex.end_date
                if ex.details:
                    base.details = ex.details
            else:
                by_url[ex.url] = ex
        results = list(by_url.values())

        # Dedup by normalized title & fill museum
        print(f"[MUSEUM] Step 6: Final deduplication by normalized title")
        uniq = []
        titles_seen = set()
        skipped_count = 0
        for i, ex in enumerate(results):
            if not ex or not ex.title: 
                skipped_count += 1
                continue
            ex.museum_name = museum_name
            key = normalize_title_key(ex.title)
            if key in titles_seen: 
                print(f"[MUSEUM] Duplicate title skipped: '{ex.title}'")
                skipped_count += 1
                continue
            titles_seen.add(key)
            uniq.append(ex)
            print(f"[MUSEUM] Added exhibition {len(uniq)}: '{ex.title}'")
        
        if skipped_count > 0:
            print(f"[MUSEUM] Skipped {skipped_count} exhibitions (duplicates or empty)")

        overall_ms = (time.perf_counter() - overall_start) * 1000
        
        # Count successful vs failed detail fetches
        scraped_count = len(detail_results)
        failed_count = max(0, len(todo) - scraped_count)
        
        print(f"\n[MUSEUM] ========== Summary for {museum_name} ==========\n")
        print(f"[MUSEUM] Total processing time: {overall_ms:.1f}ms")
        print(f"[MUSEUM] Listing fetch: {t_listing['t_total_ms']}ms")
        print(f"[MUSEUM] Listing LLM: {t_llm_listing:.1f}ms")
        print(f"[MUSEUM] Detail fetching: {t_details:.1f}ms")
        print(f"[MUSEUM] Exhibition counts:")
        print(f"[MUSEUM]   - Listings after dedup: {len(dedup_items)}")
        print(f"[MUSEUM]   - Detail candidates: {len(todo)}")
        print(f"[MUSEUM]   - Successfully scraped: {scraped_count}")
        print(f"[MUSEUM]   - Failed to scrape: {failed_count}")
        print(f"[MUSEUM]   - Final unique: {len(uniq)}")
        print(f"[MUSEUM] ================================================\n")
        
        summary = {
            "museum": museum_name,
            "listing_url": listing_url,
            "counts": {
                "listings": len(dedup_items),
                "detail_candidates": len(todo),
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


