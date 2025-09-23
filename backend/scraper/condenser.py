import time, re, hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple
import httpx
from selectolax.parser import HTMLParser

from scraper.utils import sha1, norm_space
from urllib.parse import urljoin, urlparse


from typing import List, Dict, Any, Tuple
import time, re
from urllib.parse import urljoin, urlparse
from pathlib import Path
import httpx
from selectolax.parser import HTMLParser
from .utils import norm_space, sha1

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