#!/usr/bin/env python3
"""
Museum URL validator (Edge-only, simplified).
Requires: pip install selenium webdriver-manager requests
Optional: pip install httpx
"""

import csv
import re
import time
import random
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Dict, List
from urllib.parse import urlparse

import requests
from requests.exceptions import SSLError, ConnectionError, Timeout, TooManyRedirects, RequestException

# optional httpx
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# selenium (Edge only)
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.common.exceptions import SessionNotCreatedException
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# ---------------- CONFIG ----------------
INPUT_FILE = "full_museums.csv"
OUTPUT_FILE = "museums_cleaned.csv"
FAILED_FILE = "museums_failed.csv"
MANUAL_CHECK_FILE = "museums_manual_check.csv"

MAX_WORKERS = 8
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 15
RETRIES = 2

# Only keep domains that truly need a browser
PROBLEM_DOMAINS = {
    "fondationlouisvuitton.fr": "selenium",
    "louvre.fr": "selenium",
}

DROP_STATUSES = {"not_found", "dns_error", "permanent_error", "bad_url"}
MANUAL_CHECK_STATUSES = {"timeout", "conn_error", "ssl_error"}

HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # avoid 'br'
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

CLOUDFLARE_TEXT_MARKERS = (
    "Attention Required! | Cloudflare",
    "Just a moment...",
    "Please enable JavaScript",
    "DDoS protection by Cloudflare",
    "Access denied",
    "You are being rate limited",
    "Checking your browser",
)

# ---------------- UTIL ----------------
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

def sanitize_url(u: str) -> str:
    if not u:
        return u
    u = COMMENT_RE.sub("", u).strip()
    if " " in u:
        u = u.split()[0]
    return u.rstrip(",;")

def is_http_url(u: str) -> bool:
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)

def hostname(u: str) -> str:
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""

def classify_status_code(status_code: int, text_snippet: str) -> str:
    if 200 <= status_code < 400:
        if any(marker in text_snippet for marker in CLOUDFLARE_TEXT_MARKERS):
            return "browser_blocked"
        return "valid"
    if status_code in (404, 410):
        return "not_found"
    if status_code in (401, 403, 405, 429, 503):
        return "browser_blocked"
    if 500 <= status_code < 600:
        return "server_error"
    return "unknown_status"

# ---------------- HTTP CLIENTS ----------------
def httpx_attempt(url: str) -> Tuple[str, int, str]:
    if not HTTPX_AVAILABLE:
        return "not_available", 0, url
    try:
        with httpx.Client(http2=False, follow_redirects=True, timeout=20.0) as client:
            client.headers.update(HEADERS)
            resp = client.get(url)
            bucket = classify_status_code(resp.status_code, resp.text[:2000] if resp.text else "")
            return bucket, resp.status_code, str(resp.url)
    except httpx.TimeoutException:
        print("   ⏳ httpx timeout", flush=True)
        return "timeout", 0, url
    except Exception as e:
        print(f"   ⚠️ httpx error: {e}", flush=True)
        return "conn_error", 0, url

def check_with_requests(url: str) -> Tuple[str, int, str]:
    last_status = 0
    final_url = url
    for attempt in range(1, RETRIES + 1):
        try:
            print(f"🔎 [req {attempt}/{RETRIES}] {url}", flush=True)
            session = requests.Session()
            session.headers.update(HEADERS)
            resp = session.get(url, allow_redirects=True,
                               timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                               verify=True, stream=False)
            bucket = classify_status_code(resp.status_code, resp.text[:2000] if resp.text else "")
            last_status = resp.status_code
            final_url = str(resp.url)
            print(f"   ↳ HTTP {resp.status_code} → {bucket} | {final_url}", flush=True)
            if bucket in {"valid", "browser_blocked", "not_found"}:
                return bucket, last_status, final_url
        except SSLError:
            print("   ⚠️ SSL error, trying without verification", flush=True)
            try:
                resp = session.get(url, verify=False, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
                return "ssl_warning", resp.status_code, str(resp.url)
            except Exception:
                pass
        except Timeout:
            print("   ⏳ Timeout", flush=True)
            if HTTPX_AVAILABLE:
                print("   🔄 Trying httpx/HTTP1.1", flush=True)
                bucket, status, final = httpx_attempt(url)
                if bucket in {"valid", "browser_blocked"}:
                    return bucket, status, final
        except (ConnectionError, TooManyRedirects, RequestException) as e:
            print(f"   ❌ Error: {type(e).__name__}", flush=True)

        if attempt < RETRIES:
            time.sleep(2 ** attempt + random.uniform(0, 0.5))
    return "timeout", last_status, final_url

# ---------------- EDGE (SELENIUM) ----------------
def create_edge_driver(headless: bool = True, edge_driver_path: str = ""):
    if not SELENIUM_AVAILABLE:
        raise ImportError("Selenium not available")

    # Use Microsoft's official mirror for Selenium Manager downloads
    os.environ.setdefault("SE_DRIVER_MIRROR_URL", "https://msedgedriver.microsoft.com")

    # Warn if stale drivers on PATH
    path_drv = shutil.which("msedgedriver")
    if path_drv:
        print(f"⚠️ Notice: msedgedriver found on PATH at {path_drv}. "
              "If you see version mismatches, remove or update it.", flush=True)

    opts = EdgeOptions()
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-http2")
    if headless:
        opts.add_argument("--headless=new")

    # 1) explicit path
    if edge_driver_path and os.path.exists(edge_driver_path):
        print("🌐 Setting up Edge driver (explicit path)...", flush=True)
        service = EdgeService(executable_path=edge_driver_path)
        return webdriver.Edge(service=service, options=opts)

    # 2) Selenium Manager (preferred)
    try:
        print("🌐 Setting up Edge (Selenium Manager)...", flush=True)
        return webdriver.Edge(options=opts)
    except (SessionNotCreatedException, WebDriverException) as e:
        print(f"   ❌ Selenium Manager failed for Edge: {e}", flush=True)

    # 3) webdriver-manager fallback
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager  # local import to keep top clean
        print("🌐 Falling back to webdriver-manager for Edge...", flush=True)
        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=opts)
    except Exception as e:
        print(f"   ❌ Edge (webdriver-manager) failed: {e}", flush=True)
        raise Exception("Failed to create Edge driver") from e

def selenium_check(urls: List[str], headless: bool = True) -> Dict[str, Tuple[str, int, str]]:
    results: Dict[str, Tuple[str, int, str]] = {}
    if not SELENIUM_AVAILABLE:
        print("⚠️ Selenium not available", flush=True)
        return results

    try:
        driver = create_edge_driver(headless=headless)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        try:
            # Not always necessary; ignore if unsupported.
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": HEADERS["User-Agent"]})
        except Exception:
            pass

        for url in urls:
            try:
                print(f"🚗 [selenium] {url}", flush=True)
                driver.set_page_load_timeout(30 if "fondationlouisvuitton.fr" in url else 20)
                driver.get(url)
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)  # let dynamic content settle

                final_url = driver.current_url
                snippet = driver.page_source[:2000]
                if len(driver.page_source) > 500:
                    if any(m in snippet for m in CLOUDFLARE_TEXT_MARKERS):
                        print("   ⚠️ [selenium] Blocked by protection", flush=True)
                        results[url] = ("browser_blocked", 0, final_url)
                    else:
                        print("   ✅ [selenium] Successfully loaded", flush=True)
                        results[url] = ("valid", 200, final_url)
                else:
                    print("   ⚠️ [selenium] Minimal content", flush=True)
                    results[url] = ("browser_blocked", 0, final_url)

            except TimeoutException:
                print("   ⏳ [selenium] Timeout", flush=True)
                results[url] = ("timeout", 0, url)
            except WebDriverException as e:
                print(f"   ❌ [selenium] WebDriver error: {str(e)[:100]}", flush=True)
                results[url] = ("conn_error", 0, url)
            except Exception as e:
                print(f"   ❌ [selenium] Error: {str(e)[:100]}", flush=True)
                results[url] = ("conn_error", 0, url)

        driver.quit()

    except Exception as e:
        print(f"❌ Failed to start Selenium: {e}", flush=True)
        print("   Trying with visible browser (non-headless)...", flush=True)
        if headless:
            return selenium_check(urls, headless=False)
    return results

# ---------------- PIPELINE ----------------
def process_rows(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    kept, dropped, manual = [], [], []

    requests_batch, selenium_batch = [], []
    for row in rows:
        row = dict(row)
        # Remove any None keys (from malformed CSV rows with extra columns)
        row = {k: v for k, v in row.items() if k is not None}
        raw_url = row.get("url", "").strip()
        clean = sanitize_url(raw_url)
        row["url"] = clean

        if not is_http_url(clean):
            row.update({"status": "bad_url", "http_status": "", "final_url": clean})
            dropped.append(row); continue

        host = hostname(clean)
        method = PROBLEM_DOMAINS.get(host, "requests")
        (selenium_batch if method == "selenium" else requests_batch).append(row)

    # 1) requests (concurrent)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(check_with_requests, r["url"]): r for r in requests_batch}
        for fut in as_completed(futs):
            row = futs[fut]
            bucket, http_status, final_url = fut.result()
            row.update({"status": bucket, "http_status": str(http_status or ""), "final_url": final_url})

    # 2) selenium for flagged domains
    if selenium_batch:
        se_results = selenium_check([r["url"] for r in selenium_batch])
        for row in selenium_batch:
            bucket, http_status, final_url = se_results.get(row["url"], ("conn_error", 0, row["url"]))
            row.update({"status": bucket, "http_status": str(http_status or ""), "final_url": final_url})

    # 3) retry any failures with selenium
    all_processed = requests_batch + selenium_batch
    failures = [r for r in all_processed if r["status"] in {"timeout", "conn_error", "browser_blocked"}]
    if failures and SELENIUM_AVAILABLE:
        print(f"\n🔄 Retrying {len(failures)} failed URLs with Selenium...", flush=True)
        se_retry = selenium_check([r["url"] for r in failures])
        for row in failures:
            if row["url"] in se_retry:
                bucket, http_status, final_url = se_retry[row["url"]]
                if bucket == "valid":
                    row.update({"status": bucket, "http_status": str(http_status or ""), "final_url": final_url})

    kept, dropped, manual = [], [], []
    for row in all_processed:
        s = row["status"]
        if s in DROP_STATUSES:
            print(f"❌ DROP [{s}] {row['url']}", flush=True); dropped.append(row)
        elif s in MANUAL_CHECK_STATUSES:
            print(f"⚠️ MANUAL CHECK [{s}] {row['url']}", flush=True); manual.append(row)
        else:
            print(f"✅ KEEP [{s}] {row['url']}", flush=True); kept.append(row)

    return kept, dropped, manual

def main():
    with open(INPUT_FILE, newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)
        fieldnames = [f for f in (reader.fieldnames or []) if f is not None] + ["status", "http_status", "final_url"]

    kept, dropped, manual = process_rows(rows)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=fieldnames); w.writeheader(); w.writerows(kept)

    if dropped:
        with open(FAILED_FILE, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=fieldnames); w.writeheader(); w.writerows(dropped)

    if manual:
        with open(MANUAL_CHECK_FILE, "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=fieldnames); w.writeheader(); w.writerows(manual)

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"✅ Kept rows      : {len(kept):4d}  → {OUTPUT_FILE}")
    print(f"❌ Dropped rows   : {len(dropped):4d}  → {FAILED_FILE if dropped else '(none)'}")
    print(f"⚠️  Manual check  : {len(manual):4d}  → {MANUAL_CHECK_FILE if manual else '(none)'}")
    print(f"📊 Total processed: {len(kept) + len(dropped) + len(manual):4d}")

if __name__ == "__main__":
    try:
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        requests.packages.urllib3.disable_warnings()  # type: ignore
    except Exception:
        pass
    main()
