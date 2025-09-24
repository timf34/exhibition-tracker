#!/usr/bin/env python3
"""
Fixed museum URL validator with automatic driver management
Requires: pip install requests playwright selenium webdriver-manager httpx
"""
import csv
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Dict, List, Optional
from urllib.parse import urlparse
import os, shutil

import requests
from requests.exceptions import (
    SSLError, ConnectionError, Timeout, TooManyRedirects, RequestException
)

# Try importing optional libraries
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("⚠️ httpx not installed. Install with: pip install httpx")

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️ Selenium not installed. Install with: pip install selenium")

# Import driver managers if available
try:
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False
    print("⚠️ webdriver-manager not installed. Install with: pip install webdriver-manager")

# ---------- CONFIG ----------
INPUT_FILE = "test_museums.csv"
OUTPUT_FILE = "museums_cleaned.csv"
FAILED_FILE = "museums_failed.csv"
MANUAL_CHECK_FILE = "museums_manual_check.csv"

MAX_WORKERS = 8
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 15
RETRIES = 2

# Browser preference is now forced to Edge
BROWSER_PREFERENCE = 'edge'

# Problematic domains that need special handling
PROBLEM_DOMAINS = {
    "fondationlouisvuitton.fr": "selenium",  # HTTP2 issues, needs real browser
    "britishmuseum.org": "playwright",
    "moma.org": "playwright",
    "louvre.fr": "selenium",
    "metmuseum.org": "playwright",
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
    "Accept-Encoding": "gzip, deflate",  # Removed 'br' which can cause issues
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
    "Checking your browser"
)

# ---------- UTIL ----------
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

def sanitize_url(u: str) -> str:
    """Clean up URL from CSV"""
    if not u:
        return u
    u = COMMENT_RE.sub("", u).strip()
    if " " in u:
        u = u.split()[0]
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

def classify_status_code(status_code: int, text_snippet: str, headers: Dict[str, str]) -> str:
    if 200 <= status_code < 400:
        # Check for JS challenges even on 200
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

# ---------- HTTPX ATTEMPT (HTTP/1.1 fallback) ----------
def httpx_attempt(url: str) -> Tuple[str, int, str]:
    """Try with httpx using HTTP/1.1"""
    if not HTTPX_AVAILABLE:
        return "not_available", 0, url
    
    try:
        # Force HTTP/1.1 to avoid HTTP/2 protocol errors
        with httpx.Client(http2=False, follow_redirects=True, timeout=20.0) as client:
            client.headers.update(HEADERS)
            resp = client.get(url)
            bucket = classify_status_code(
                resp.status_code, 
                resp.text[:2000] if resp.text else "", 
                dict(resp.headers)
            )
            return bucket, resp.status_code, str(resp.url)
    except httpx.TimeoutException:
        print(f"   ⏳ httpx timeout", flush=True)
        return "timeout", 0, url
    except Exception as e:
        print(f"   ⚠️ httpx error: {e}", flush=True)
        return "conn_error", 0, url

# ---------- REQUESTS STAGE ----------
def check_with_requests(url: str) -> Tuple[str, int, str]:
    """Standard requests attempt"""
    last_status = 0
    final_url = url
    
    # For fondationlouisvuitton.fr, skip directly to httpx
    if "fondationlouisvuitton.fr" in url and HTTPX_AVAILABLE:
        print(f"🔄 [httpx/HTTP1.1] {url}", flush=True)
        return httpx_attempt(url)
    
    for attempt in range(1, RETRIES + 1):
        try:
            print(f"🔎 [req {attempt}/{RETRIES}] {url}", flush=True)
            
            # Create session for better connection handling
            session = requests.Session()
            session.headers.update(HEADERS)
            
            resp = session.get(
                url,
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                verify=True,
                stream=False  # Don't stream, get full response
            )
            
            bucket = classify_status_code(
                resp.status_code, 
                resp.text[:2000] if resp.text else "", 
                resp.headers
            )
            last_status = resp.status_code
            final_url = resp.url
            
            print(f"   ↳ HTTP {resp.status_code} → {bucket} | {final_url}", flush=True)
            
            if bucket in {"valid", "browser_blocked", "not_found"}:
                return bucket, last_status, final_url
                
        except SSLError:
            print(f"   ⚠️ SSL error, trying without verification", flush=True)
            try:
                resp = session.get(url, verify=False, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
                return "ssl_warning", resp.status_code, resp.url
            except Exception:
                pass
                
        except Timeout:
            print(f"   ⏳ Timeout", flush=True)
            # Try httpx with HTTP/1.1
            if HTTPX_AVAILABLE:
                print(f"   🔄 Trying httpx/HTTP1.1", flush=True)
                bucket, status, final = httpx_attempt(url)
                if bucket in {"valid", "browser_blocked"}:
                    return bucket, status, final
                    
        except (ConnectionError, TooManyRedirects, RequestException) as e:
            print(f"   ❌ Error: {type(e).__name__}", flush=True)
        
        if attempt < RETRIES:
            time.sleep(2 ** attempt + random.uniform(0, 0.5))
    
    return "timeout", last_status, final_url

# ---------- PLAYWRIGHT STAGE ----------
def playwright_check(urls: List[str]) -> Dict[str, Tuple[str, int, str]]:
    """Playwright with better error handling"""
    results: Dict[str, Tuple[str, int, str]] = {}
    
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("⚠️ Playwright not available", flush=True)
        return results
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--no-sandbox',
                    '--disable-http2',  # Force HTTP/1.1
                ]
            )
        except Exception as e:
            print(f"❌ Failed to launch Playwright browser: {e}", flush=True)
            return results
        
        for url in urls:
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={'width': 1920, 'height': 1080},
                ignore_https_errors=True,
            )
            page = context.new_page()
            
            try:
                print(f"🎭 [playwright] {url}", flush=True)
                
                # Add random delay to appear more human
                page.wait_for_timeout(random.randint(1000, 3000))
                
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status = resp.status if resp else 0
                final_url = page.url
                content = page.content()[:2000]
                
                bucket = classify_status_code(status or 200, content, {})
                if status == 0 and content and len(content) > 100:
                    bucket = "valid"
                    
                print(f"   ↳ [playwright] HTTP {status} → {bucket}", flush=True)
                results[url] = (bucket, status, final_url)
                
            except PWTimeout:
                print(f"   ⏳ [playwright] Timeout", flush=True)
                results[url] = ("timeout", 0, url)
            except Exception as e:
                print(f"   ❌ [playwright] Error: {e}", flush=True)
                results[url] = ("conn_error", 0, url)
            finally:
                context.close()
        
        browser.close()
    
    return results

# ---------- SELENIUM STAGE ----------
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService

def create_selenium_driver(headless: bool = True, edge_driver_path: str = ""):
    """
    Create an Edge Selenium driver with the same strategy as the Substack scraper:
    1) Use explicit driver path if provided
    2) Try Selenium Manager (with official ms mirror)
    3) Fallback to webdriver-manager
    """
    if not SELENIUM_AVAILABLE:
        raise ImportError("Selenium not available")
    if not WEBDRIVER_MANAGER_AVAILABLE:
        raise ImportError("webdriver-manager not available. Install with: pip install webdriver-manager")

    # Use Microsoft's official msedgedriver mirror (helps when azureedge is flaky)
    os.environ.setdefault("SE_DRIVER_MIRROR_URL", "https://msedgedriver.microsoft.com")

    # Warn if stale drivers on PATH (they can cause mismatches)
    for drv in ("chromedriver", "msedgedriver"):
        path_drv = shutil.which(drv)
        if path_drv:
            print(f"⚠️ Notice: {drv} found on PATH at {path_drv}. "
                  f"If you see version mismatches, remove or update it.", flush=True)

    # Edge options (headless/new)
    edge_options = EdgeOptions()
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_argument("--disable-http2")
    if headless:
        edge_options.add_argument("--headless=new")

    # 1) explicit driver path
    if edge_driver_path and os.path.exists(edge_driver_path):
        print("🌐 Setting up Edge driver (explicit path)...", flush=True)
        service = EdgeService(executable_path=edge_driver_path)
        return webdriver.Edge(service=service, options=edge_options)

    # 2) Selenium Manager (preferred)
    try:
        print("🌐 Setting up Edge (Selenium Manager)...", flush=True)
        return webdriver.Edge(options=edge_options)
    except (SessionNotCreatedException, WebDriverException) as e:
        print(f"   ❌ Selenium Manager failed for Edge: {e}", flush=True)

    # 3) webdriver-manager fallback
    try:
        print("🌐 Falling back to webdriver-manager for Edge...", flush=True)
        service = EdgeService(EdgeChromiumDriverManager().install())
        return webdriver.Edge(service=service, options=edge_options)
    except Exception as e:
        print(f"   ❌ Edge (webdriver-manager) failed: {e}", flush=True)
        raise Exception("Failed to create Edge driver") from e

def selenium_check(urls: List[str], headless: bool = True) -> Dict[str, Tuple[str, int, str]]:
    """Selenium with Edge-only driver management"""
    results: Dict[str, Tuple[str, int, str]] = {}
    
    if not SELENIUM_AVAILABLE:
        print("⚠️ Selenium not available", flush=True)
        return results
    
    try:
        driver = create_selenium_driver(headless=headless)
        # Anti-detection measures
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        try:
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": HEADERS["User-Agent"]})
        except Exception:
            pass
        
        for url in urls:
            try:
                print(f"🚗 [selenium] {url}", flush=True)
                
                # For fondationlouisvuitton.fr, add extra wait time
                if "fondationlouisvuitton.fr" in url:
                    driver.set_page_load_timeout(30)
                else:
                    driver.set_page_load_timeout(20)
                
                driver.get(url)
                
                # Wait strategies based on domain
                if "fondationlouisvuitton.fr" in url:
                    # Wait longer for this problematic site
                    time.sleep(5)
                    try:
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                    except:
                        pass  # Continue even if wait times out
                else:
                    # Standard wait
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                
                # Additional wait for dynamic content
                time.sleep(2)
                
                # Get page info
                final_url = driver.current_url
                page_source = driver.page_source[:2000]
                
                # Check if we got real content
                if len(driver.page_source) > 500:
                    # Check for Cloudflare or other blocks
                    if any(m in page_source for m in CLOUDFLARE_TEXT_MARKERS):
                        print(f"   ⚠️ [selenium] Blocked by protection", flush=True)
                        results[url] = ("browser_blocked", 0, final_url)
                    else:
                        print(f"   ✅ [selenium] Successfully loaded", flush=True)
                        results[url] = ("valid", 200, final_url)
                else:
                    print(f"   ⚠️ [selenium] Minimal content", flush=True)
                    results[url] = ("browser_blocked", 0, final_url)
                    
            except TimeoutException:
                print(f"   ⏳ [selenium] Timeout", flush=True)
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
        # Try once more without headless if it failed
        if headless:
            return selenium_check(urls, headless=False)
    
    return results

# ---------- MAIN PIPELINE ----------
def process_rows(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    """Returns (kept_rows, dropped_rows, manual_check_rows)"""
    kept, dropped, manual = [], [], []
    
    # Categorize URLs by method
    requests_batch = []
    playwright_batch = []
    selenium_batch = []
    
    for row in rows:
        row = dict(row)
        raw_url = row.get("url", "").strip()
        clean = sanitize_url(raw_url)
        row["url"] = clean
        
        if not is_http_url(clean):
            row["status"] = "bad_url"
            row["http_status"] = ""
            row["final_url"] = clean
            dropped.append(row)
            continue
        
        host = hostname(clean)
        method = PROBLEM_DOMAINS.get(host, "requests")
        
        if method == "selenium":
            selenium_batch.append(row)
        elif method == "playwright":
            playwright_batch.append(row)
        else:
            requests_batch.append(row)
    
    # 1. Process with requests (concurrent)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(check_with_requests, r["url"]): r for r in requests_batch}
        for fut in as_completed(futs):
            row = futs[fut]
            bucket, http_status, final_url = fut.result()
            row["status"] = bucket
            row["http_status"] = str(http_status or "")
            row["final_url"] = final_url
    
    # 2. Process with Playwright
    if playwright_batch:
        pw_results = playwright_check([r["url"] for r in playwright_batch])
        for row in playwright_batch:
            bucket, http_status, final_url = pw_results.get(row["url"], ("conn_error", 0, row["url"]))
            row["status"] = bucket
            row["http_status"] = str(http_status or "")
            row["final_url"] = final_url
    
    # 3. Process with Selenium (includes problematic sites)
    if selenium_batch:
        se_results = selenium_check([r["url"] for r in selenium_batch])
        for row in selenium_batch:
            bucket, http_status, final_url = se_results.get(row["url"], ("conn_error", 0, row["url"]))
            row["status"] = bucket
            row["http_status"] = str(http_status or "")
            row["final_url"] = final_url
    
    # 4. Retry failures with Selenium
    all_processed = requests_batch + playwright_batch + selenium_batch
    failures = [r for r in all_processed if r["status"] in {"timeout", "conn_error", "browser_blocked"}]
    
    if failures and SELENIUM_AVAILABLE and WEBDRIVER_MANAGER_AVAILABLE:
        print(f"\n🔄 Retrying {len(failures)} failed URLs with Selenium...", flush=True)
        se_retry = selenium_check([r["url"] for r in failures])
        for row in failures:
            if row["url"] in se_retry:
                bucket, http_status, final_url = se_retry[row["url"]]
                if bucket == "valid":  # Only update if successful
                    row["status"] = bucket
                    row["http_status"] = str(http_status or "")
                    row["final_url"] = final_url
    
    # 5. Categorize results
    for row in all_processed:
        status = row["status"]
        if status in DROP_STATUSES:
            print(f"❌ DROP [{status}] {row['url']}", flush=True)
            dropped.append(row)
        elif status in MANUAL_CHECK_STATUSES:
            print(f"⚠️ MANUAL CHECK [{status}] {row['url']}", flush=True)
            manual.append(row)
        else:
            print(f"✅ KEEP [{status}] {row['url']}", flush=True)
            kept.append(row)
    
    return kept, dropped, manual

def main():
    # Read input
    with open(INPUT_FILE, newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or []) + ["status", "http_status", "final_url"]
    
    # Process
    kept, dropped, manual = process_rows(rows)
    
    # Write outputs
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)
    
    if dropped:
        with open(FAILED_FILE, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(dropped)
    
    if manual:
        with open(MANUAL_CHECK_FILE, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manual)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"✅ Kept rows      : {len(kept):4d}  → {OUTPUT_FILE}")
    print(f"❌ Dropped rows   : {len(dropped):4d}  → {FAILED_FILE if dropped else '(none)'}")
    print(f"⚠️  Manual check  : {len(manual):4d}  → {MANUAL_CHECK_FILE if manual else '(none)'}")
    print(f"📊 Total processed: {len(kept) + len(dropped) + len(manual):4d}")
    
    # Check available tools
    print("\n" + "="*60)
    print("AVAILABLE TOOLS")
    print("="*60)
    print(f"httpx:              {'✅ Available' if HTTPX_AVAILABLE else '❌ Not installed'}")
    print(f"Selenium:           {'✅ Available' if SELENIUM_AVAILABLE else '❌ Not installed'}")
    print(f"webdriver-manager:  {'✅ Available' if WEBDRIVER_MANAGER_AVAILABLE else '❌ Not installed'}")
    print()
    
    if not WEBDRIVER_MANAGER_AVAILABLE:
        print("💡 IMPORTANT: Install webdriver-manager to fix driver issues:")
        print("   pip install webdriver-manager")
        print("   This will automatically download the correct driver version!")

if __name__ == "__main__":
    try:
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        requests.packages.urllib3.disable_warnings()  # type: ignore
    except:
        pass
    main()