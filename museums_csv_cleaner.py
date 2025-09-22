# validate_museum_urls_hybrid.py
# Python 3.9+
import csv
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Dict, List
from urllib.parse import urlparse

import requests
from requests.exceptions import (
    SSLError, ConnectionError, Timeout, TooManyRedirects, RequestException
)

# ---------- CONFIG ----------
INPUT_FILE = "museums.csv"
OUTPUT_FILE = "museums_cleaned.csv"
FAILED_FILE = "museums_failed.csv"

MAX_WORKERS = 16
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 10
RETRIES = 2  # quick retries; Playwright is the heavy fallback

# Domains that are known to block bots / need JS. We send them straight to Playwright.
BROWSER_ONLY_DOMAINS = {
    "fondationlouisvuitton.fr",
    "britishmuseum.org",
    "moma.org",
    # add more if you notice persistent blocking:
    # "louvre.fr", "metmuseum.org", ...
}

# Only drop these outcomes. Everything else is kept.
DROP_STATUSES = {"not_found", "dns_error", "timeout", "conn_error", "ssl_error", "bad_url"}

HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

CLOUDFLARE_TEXT_MARKERS = (
    "Attention Required! | Cloudflare",
    "Just a moment...",
    "Please enable JavaScript",
    "DDoS protection by Cloudflare",
)
CLOUDFLARE_HEADERS = ("cf-ray", "cf-cache-status")


# ---------- UTIL ----------
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

def sanitize_url(u: str) -> str:
    """Strip HTML comments and trailing junk from URL cells."""
    if not u:
        return u
    u = COMMENT_RE.sub("", u).strip()
    # Some users add trailing comments without HTML markers; keep only the first whitespace-separated token
    # (URLs should not legally contain spaces)
    if " " in u:
        u = u.split()[0]
    # Remove trailing commas/semicolons if someone pasted with punctuation
    u = u.rstrip(",;")
    return u

def is_http_url(u: str) -> bool:
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)

def hostname(u: str) -> str:
    try:
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""


# ---------- CLASSIFIERS ----------
def classify_status_code(status_code: int, text_snippet: str, headers: Dict[str, str]) -> str:
    if 200 <= status_code < 400:
        return "valid"
    if status_code in (404, 410):
        return "not_found"
    if status_code in (401, 403, 405, 429, 503):
        h_lower = {k.lower(): v for k, v in headers.items()}
        if any(h in h_lower for h in CLOUDFLARE_HEADERS) or any(m in text_snippet for m in CLOUDFLARE_TEXT_MARKERS):
            return "browser_blocked"
        return "browser_blocked"
    if 500 <= status_code < 600:
        return "server_error"
    return "server_error"


# ---------- REQUESTS STAGE ----------
def requests_attempt(url: str, verify_ssl: bool = True) -> Tuple[str, int, str]:
    resp = requests.get(
        url,
        headers=HEADERS,
        allow_redirects=True,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        verify=verify_ssl,
    )
    bucket = classify_status_code(resp.status_code, resp.text[:2000] if resp.text else "", resp.headers)
    return bucket, resp.status_code, resp.url

def check_with_requests(url: str) -> Tuple[str, int, str]:
    last_status = 0
    final_url = url
    for attempt in range(1, RETRIES + 1):
        try:
            print(f"🔎 [req {attempt}/{RETRIES}] {url}", flush=True)
            bucket, http_status, final_url = requests_attempt(url, verify_ssl=True)
            last_status = http_status
            print(f"   ↳ HTTP {http_status} → {bucket} | {final_url}", flush=True)
            if bucket in {"valid", "browser_blocked", "server_error", "not_found"}:
                return bucket, last_status, final_url
        except SSLError as e:
            print(f"   ⚠️ SSL error: {e} (retry no-verify)", flush=True)
            try:
                bucket, http_status, final_url = requests_attempt(url, verify_ssl=False)
                last_status = http_status
                print(f"   ↳ (no-verify) HTTP {http_status} → {bucket} | {final_url}", flush=True)
                if bucket in {"valid", "browser_blocked", "server_error", "not_found"}:
                    return bucket, last_status, final_url
            except Exception as e2:
                print(f"   ❌ SSL fallback failed: {e2}", flush=True)
        except Timeout as e:
            print(f"   ⏳ Timeout: {e}", flush=True)
        except ConnectionError as e:
            print(f"   ❌ Connection error: {e}", flush=True)
        except TooManyRedirects as e:
            print(f"   🔁 Too many redirects: {e}", flush=True)
        except RequestException as e:
            print(f"   ❌ Request exception: {e}", flush=True)

        # short backoff
        time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.3))

    # If we reach here, requests couldn't confirm
    # Distinguish timeout/conn_error generically
    return "timeout", last_status, final_url


# ---------- PLAYWRIGHT STAGE ----------
def playwright_check(urls: List[str]) -> Dict[str, Tuple[str, int, str]]:
    """
    Returns dict[url] = (bucket, http_status, final_url)
    """
    results: Dict[str, Tuple[str, int, str]] = {}
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except Exception as e:
        print(f"\n⚠️ Playwright not available: {e}\n"
              f"Install with: pip install playwright && playwright install\n", flush=True)
        return results

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        # A single page we reuse speeds things up
        page = context.new_page()

        for url in urls:
            try:
                print(f"🧭 [pw] Navigating: {url}", flush=True)
                resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                status = resp.status if resp else 0
                final_url = resp.url if resp else url
                content = page.content()[:2000]
                # Heuristic: if we got DOM loaded, it's likely reachable
                bucket = classify_status_code(status or 200, content, {})
                # If status unknown but DOM loaded, treat as valid
                if status == 0 and content:
                    bucket = "valid"
                print(f"   ↳ [pw] HTTP {status} → {bucket} | {final_url}", flush=True)
                results[url] = (bucket, status, final_url)
            except PWTimeout:
                print(f"   ⏳ [pw] Timeout loading {url}", flush=True)
                results[url] = ("timeout", 0, url)
            except Exception as e:
                print(f"   ❌ [pw] Error on {url}: {e}", flush=True)
                results[url] = ("conn_error", 0, url)

        context.close()
        browser.close()
    return results


# ---------- PIPELINE ----------
def process_rows(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Returns (kept_rows, dropped_rows)."""
    # First pass: sanitize and quick route to requests or playwright
    tasks = []
    prepared: List[Dict[str, str]] = []
    to_playwright_first: List[Dict[str, str]] = []

    for row in rows:
        row = dict(row)
        raw_url = row.get("url", "").strip()
        clean = sanitize_url(raw_url)
        row["url"] = clean

        if not is_http_url(clean):
            row["status"] = "bad_url"
            row["http_status"] = ""
            row["final_url"] = clean
            prepared.append(row)
            continue

        host = hostname(clean)
        if host in BROWSER_ONLY_DOMAINS:
            to_playwright_first.append(row)
        else:
            prepared.append(row)

    kept, dropped = [], []

    # 1) Playwright for the browser-only domains immediately
    if to_playwright_first:
        pw_urls = [r["url"] for r in to_playwright_first]
        pw_res = playwright_check(pw_urls)
        for r in to_playwright_first:
            u = r["url"]
            bucket, http_status, final_url = pw_res.get(u, ("conn_error", 0, u))
            r["status"] = bucket
            r["http_status"] = str(http_status or "")
            r["final_url"] = final_url
            if bucket in DROP_STATUSES:
                print(f"❌ DROP [{bucket}] {u}", flush=True)
                dropped.append(r)
            else:
                print(f"✅ KEEP [{bucket}] {u}", flush=True)
                kept.append(r)

    # 2) Requests pass (concurrent) for the rest
    to_requests = [r for r in prepared if "status" not in r]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(check_with_requests, r["url"]): r for r in to_requests}
        for fut in as_completed(futs):
            r = futs[fut]
            url = r["url"]
            bucket, http_status, final_url = fut.result()
            r["status"] = bucket
            r["http_status"] = str(http_status or "")
            r["final_url"] = final_url

    # 3) Fallback with Playwright for any unresolved/blocked/timeouts
    need_pw = [r for r in to_requests if r["status"] in {"timeout", "conn_error", "browser_blocked", "server_error"}]
    if need_pw:
        pw_urls = [r["url"] for r in need_pw]
        pw_res = playwright_check(pw_urls)
        for r in need_pw:
            u = r["url"]
            if u in pw_res:
                bucket, http_status, final_url = pw_res[u]
                # Prefer Playwright’s verdict if it’s better than a failure
                if bucket in {"valid", "browser_blocked"} or r["status"] in {"timeout", "conn_error"}:
                    r["status"] = bucket
                    r["http_status"] = str(http_status or "")
                    r["final_url"] = final_url

    # 4) Finalize keep/drop decisions
    for r in to_requests:
        if r["status"] in DROP_STATUSES:
            print(f"❌ DROP [{r['status']}] {r['url']}", flush=True)
            dropped.append(r)
        else:
            print(f"✅ KEEP [{r['status']}] {r['url']}", flush=True)
            kept.append(r)

    return kept, dropped


def main():
    with open(INPUT_FILE, newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or []) + ["status", "http_status", "final_url"]

    kept, dropped = process_rows(rows)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    if dropped:
        with open(FAILED_FILE, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(dropped)

    print("\n====== SUMMARY ======")
    print(f"Kept rows   : {len(kept)}  → {OUTPUT_FILE}")
    print(f"Dropped rows: {len(dropped)}  → {FAILED_FILE if dropped else '(none)'}")


if __name__ == "__main__":
    try:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
    except Exception:
        pass
    main()
