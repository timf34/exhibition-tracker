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
        # --- Selenium fallback config (matches the working Edge-only script) ---
        self._driver = None
        self._selenium_headless = True          # default headless; we'll flip to False if needed
        self._edge_driver_path = os.environ.get("EDGE_DRIVER_PATH", "")  # optional
        os.environ.setdefault("SE_DRIVER_MIRROR_URL", "https://msedgedriver.microsoft.com")  # use official Edge mirror

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

            # Quick retry with HTTP/1.1 (several museum sites reset HTTP/2 streams)
            try:
                print("[FETCH] Retrying with HTTP/1.1 (httpx http2=False)…")
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    http2=False,
                    headers=self.client.headers,
                    timeout=self.timeout,
                ) as c1:
                    r2 = await c1.get(url)
                    r2.raise_for_status()
                    html = r2.text
                    if use_cache:
                        key.write_text(html, encoding="utf-8")
                        print(f"[FETCH] Cached to: {key.name}")
                    elapsed = (time.perf_counter() - start) * 1000
                    print(f"[FETCH] HTTP/1.1 retry successful in {elapsed:.1f}ms")
                    return html, False, elapsed
            except Exception as e1:
                print(f"[FETCH] HTTP/1.1 retry failed: {e1}")

            # ---- Fallback to Selenium Edge ----
            try:
                print("[FETCH] Falling back to Selenium (Edge)…")
                html = self._selenium_fetch(url)
                # DO NOT raise on minimal HTML; keep what we have.
                if use_cache and html:
                    key.write_text(html, encoding="utf-8")
                    print(f"[FETCH] Cached Selenium HTML to: {key.name}")
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[FETCH] Selenium fetch completed in {elapsed:.1f}ms (chars={len(html)})")
                return html, False, elapsed
            except Exception as se:
                print(f"[FETCH] Selenium fallback failed: {se}")
                raise


    def _selenium_fetch(self, url: str) -> str:
        """Fetch HTML via Edge; tolerate renderer timeouts and keep whatever DOM we get."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, WebDriverException
        import time

        def _navigate_and_wait(drv):
            try:
                drv.set_page_load_timeout(30)
            except Exception:
                pass

            try:
                drv.get(url)
                # Prefer a text-based readiness, not full load.
                try:
                    WebDriverWait(drv, 20).until(
                        lambda d: d.execute_script(
                            "return (document.readyState==='interactive' || document.readyState==='complete')"
                            " && document.body && document.body.innerText && document.body.innerText.length > 500;"
                        )
                    )
                except Exception:
                    # Fallback: just ensure <body> exists.
                    WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            except TimeoutException:
                # Stop the load and keep what we have.
                try:
                    drv.execute_script("window.stop();")
                except Exception:
                    pass

            # Nudge lazy content
            try:
                drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(2)
            return drv.page_source or ""

        # Try headless (or current mode)
        drv = self._get_edge_driver()
        html = _navigate_and_wait(drv)

        # If DOM is still too thin, one-shot visible retry
        if (not html) or (len(html) < 500):
            if self._selenium_headless:
                # Recreate driver non-headless once
                try:
                    drv.quit()
                except Exception:
                    pass
                self._driver = None
                self._selenium_headless = False
                drv = self._get_edge_driver()
                html = _navigate_and_wait(drv)

        return html or ""

    def _get_edge_driver(self):
        """Create/reuse a single Edge driver with stable flags."""
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService
        from selenium.common.exceptions import WebDriverException

        if self._driver is not None:
            return self._driver

        opts = EdgeOptions()
        # Don't wait for every subresource.
        opts.page_load_strategy = "eager"
        if self._selenium_headless:
            opts.add_argument("--headless=new")

        # Stability flags (mirrors the validator)
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-http2")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-features=IsolateOrigins,site-per-process,RendererCodeIntegrity")

        # 1) explicit path if provided
        if self._edge_driver_path:
            self._driver = webdriver.Edge(service=EdgeService(self._edge_driver_path), options=opts)
            return self._driver

        # 2) Selenium Manager (preferred)
        try:
            self._driver = webdriver.Edge(options=opts)
            return self._driver
        except WebDriverException:
            pass

        # 3) webdriver-manager fallback
        try:
            from webdriver_manager.microsoft import EdgeChromiumDriverManager
            service = EdgeService(EdgeChromiumDriverManager().install())
            self._driver = webdriver.Edge(service=service, options=opts)
            return self._driver
        except Exception as e:
            raise RuntimeError(f"Failed to create Edge driver: {e}")


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
