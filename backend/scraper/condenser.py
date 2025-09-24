import time, re, hashlib, os
from pathlib import Path
from typing import List, Dict, Any, Tuple
import httpx
from selectolax.parser import HTMLParser

from backend.scraper.utils import sha1, norm_space
from urllib.parse import urljoin, urlparse


class PageCondenser:
    # Include more tags where dates and info might hide (from v2)
    ALLOWED_TEXT_TAGS = {"h1","h2","h3","h4","p","li","time","figcaption","span","dt","dd","em","strong"}
    MAIN_SELECTORS = ["main", "#content", "#swup", "[role=main]", "article", ".content", ".exhibitions", "#exhibitions"]

    def __init__(self, cache_dir=".cache_html", timeout=20.0, http2=True, selenium_headless=True, edge_driver_path:str=""):
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(exist_ok=True)
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            http2=http2,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Exhibitions/1.1)"},
            timeout=self.timeout,
        )
        # --- Selenium / Edge fallback (lazy-init) ---
        self._driver = None
        self._selenium_headless = selenium_headless
        self._edge_driver_path = edge_driver_path
        # Use Microsoft's official msedgedriver mirror for Selenium Manager downloads
        os.environ.setdefault("SE_DRIVER_MIRROR_URL", "https://msedgedriver.microsoft.com")

    async def close(self):
        await self.client.aclose()
        # Cleanly close Selenium if we created it
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    # --------- Networking ----------
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
            elapsed = (time.perf_counter() - start) * 1000
            print(f"[FETCH] Fetch completed in {elapsed:.1f}ms")
            return html, False, elapsed
        except Exception as e:
            print(f"[FETCH] ERROR with httpx: {e}")
            # ---- Fallback to Selenium Edge ----
            try:
                print("[FETCH] Falling back to Selenium (Edge)...")
                html = self._selenium_fetch(url)
                if not html or len(html) < 200:
                    raise RuntimeError("Selenium returned minimal/empty HTML")
                if use_cache:
                    key.write_text(html, encoding="utf-8")
                    print(f"[FETCH] Cached Selenium HTML to: {key.name}")
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[FETCH] Selenium fetch completed in {elapsed:.1f}ms")
                return html, False, elapsed
            except Exception as se:
                print(f"[FETCH] Selenium fallback failed: {se}")
                # Re-raise original httpx error for upstream handling
                raise

    def _selenium_fetch(self, url: str) -> str:
        """Blocking Selenium (Edge) fetch; returns page_source."""
        drv = self._get_edge_driver()
        # Use a slightly longer timeout for tricky pages
        try:
            drv.set_page_load_timeout(30)
        except Exception:
            pass
        drv.get(url)

        # Try to wait for a body element
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            # continue anyway
            pass

        # small settle time for dynamic content
        time.sleep(2)
        return drv.page_source or ""

    def _get_edge_driver(self):
        """Lazy-create a single Edge driver and reuse it."""
        if self._driver is not None:
            return self._driver

        # Try Selenium Manager first (preferred)
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options as EdgeOptions
            from selenium.webdriver.edge.service import Service as EdgeService
            from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

            opts = EdgeOptions()
            if self._selenium_headless:
                opts.add_argument("--headless=new")
            # reasonable defaults
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-http2")

            if self._edge_driver_path:
                print("[SE] Using explicit EdgeDriver path")
                service = EdgeService(executable_path=self._edge_driver_path)
                self._driver = webdriver.Edge(service=service, options=opts)
                return self._driver

            print("[SE] Creating Edge driver via Selenium Manager…")
            self._driver = webdriver.Edge(options=opts)
            return self._driver
        except Exception as e_first:
            print(f"[SE] Selenium Manager failed: {e_first}. Trying webdriver-manager…")
            # Fallback to webdriver-manager (requires network)
            try:
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                from selenium.webdriver.edge.service import Service as EdgeService
                from selenium import webdriver
                service = EdgeService(EdgeChromiumDriverManager().install())
                from selenium.webdriver.edge.options import Options as EdgeOptions
                opts = EdgeOptions()
                if self._selenium_headless:
                    opts.add_argument("--headless=new")
                opts.add_argument("--disable-gpu")
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
                opts.add_argument("--disable-http2")
                self._driver = webdriver.Edge(service=service, options=opts)
                return self._driver
            except Exception as e_second:
                raise RuntimeError(f"Failed to create Edge driver: {e_second}") from e_second

    # --------- Condense pipeline ----------
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
            print(f"[CONDENSE] Link filtering: {total_links} total → {len(out)} kept "
                  f"(skipped: {skipped_counts['no_href_text']} no href/text, "
                  f"{skipped_counts['external']} external, {skipped_counts['duplicate']} duplicate)")
        return out

    def condense_html(self, html: str, base_url: str, limit_text_chars=16000) -> Dict[str, Any]:
        print(f"[CONDENSE] Starting HTML condensation ({len(html)} chars input)")
        t_start = time.perf_counter()

        doc = HTMLParser(html)
        body = doc.body or doc
        main = self._choose_main(body)
        print(f"[CONDENSE] Selected main content area: {getattr(main, 'tag', 'root')}")

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

        # Add meta descriptions
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
            "t_fetch_ms": round(t_fetch, 1),
            "t_condense_ms": round(t_condense, 1),
            "t_total_ms": round(t_fetch + t_condense, 1),
            "from_cache": cached
        }
        result["url"] = url

        print(f"[CONDENSE_URL] Completed in {total_time:.1f}ms (fetch: {t_fetch:.1f}ms, condense: {t_condense:.1f}ms)")
        return result
