#!/usr/bin/env python3
"""
condense_exhibitions.py
Fast HTML condenser for museum listing pages:
- returns plain visible text for LLM
- extracts anchors (href + text + short context)
- detects pagination / "see more" links
- minimal attributes, no heavy DOM walking

Usage:
  python condense_exhibitions.py https://www.nationalgallery.ie/art-and-artists/exhibitions
"""

import sys, re, json, time, hashlib
from urllib.parse import urljoin, urlparse
from pathlib import Path
import httpx
from selectolax.parser import HTMLParser

# ------------------------ helpers ------------------------

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def same_domain(href: str, base: str) -> bool:
    try:
        return urlparse(href).netloc in ("", urlparse(base).netloc)
    except Exception:
        return True

EXHIBIT_HINT = re.compile(r"\b(exhibition|exhibitions|exhibit|galleries?)\b", re.I)
EVENT_HINT   = re.compile(r"\b(event|events|calendar)\b", re.I)
PAGINATION_HINT = re.compile(r"\b(next|more|see all|load more|view all|past exhibitions|previous)\b", re.I)

ALLOWED_TEXT_TAGS = {"h1","h2","h3","h4","p","li","time","figcaption"}
MAIN_SELECTORS = ["main", "#content", "#swup", "[role=main]", "article", ".content", ".exhibitions", "#exhibitions"]

def take_text(node, limit_chars=12000):
    """Collect visible text in reading order from allowed tags only, trimmed to limit."""
    lines = []
    count = 0
    for tag in ALLOWED_TEXT_TAGS:
        for el in node.css(tag):
            t = norm_space(el.text())
            if not t:
                continue
            lines.append(t)
            count += len(t) + 1
            if count >= limit_chars:
                return "\n".join(lines)[:limit_chars]
    # fallback if nothing collected
    text = norm_space(node.text())[:limit_chars]
    return "\n".join(lines) if lines else text

def nearest_context(a_node):
    """Short context from nearest substantial ancestor block."""
    hops, node = 0, a_node.parent
    while node and hops < 4:
        t = norm_space(node.text())
        if len(t) >= 40:
            return t[:240]
        node = node.parent
        hops += 1
    return ""

def collect_anchors(node, base_url, max_items=800):
    """Collect anchors with text + resolved href + short context; de-dup by (href,text)."""
    seen, out = set(), []
    for a in node.css("a"):
        href = (a.attributes.get("href") or "").strip()
        text = norm_space(a.text())[:180]
        if not href or not text:
            continue
        href = urljoin(base_url, href)
        if not same_domain(href, base_url):
            # usually skip external anchors; keep if it obviously looks like an exhibition link
            if "exhibition" not in text.lower():
                continue
        key = (href, text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": text,
            "href": href,
            "context": nearest_context(a),
        })
        if len(out) >= max_items:
            break
    return out

def classify_anchor(a):
    text = (a["text"] + " " + a.get("context","")).lower()
    href = a["href"].lower()
    is_exhibition = ("exhibit" in text or "/exhibitions" in href or "exhibition" in href) and not ("/events" in href or "calendar" in href or EVENT_HINT.search(text))
    is_event = "/events" in href or EVENT_HINT.search(text)
    is_pager = PAGINATION_HINT.search(text) is not None
    return ("exhibition" if is_exhibition else "event" if is_event else "other",
            "pagination" if is_pager else None)

def choose_main(root):
    # prefer main-like containers; fall back to body
    for sel in MAIN_SELECTORS:
        node = root.css_first(sel)
        if node:
            return node
    return root

# ------------------------ fetch + condense ------------------------

def sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def fetch_html(url: str, timeout=20.0, cache=True):
    """Simple fetch with tiny file cache for speed during dev."""
    cache_dir = Path(".cache_html"); cache_dir.mkdir(exist_ok=True)
    key = cache_dir / (sha1(url) + ".html")
    if cache and key.exists():
        return key.read_text(encoding="utf-8", errors="ignore"), True
    with httpx.Client(follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ExhibitionsCondense/1.0)"
    }, timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
        html = r.text
        if cache:
            key.write_text(html, encoding="utf-8")
        return html, False

def condense(url: str, limit_text_chars=12000):
    t0 = time.perf_counter()
    html, from_cache = fetch_html(url)
    t_fetch = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    doc = HTMLParser(html)
    root = doc.body or doc
    main = choose_main(root)

    # remove obvious noise nodes before extraction (fast prune)
    for sel in ("script", "style", "noscript", "template", "svg", "iframe"):
        for n in main.css(sel):
            n.decompose()

    # extract anchors (then we can filter down to exhibitions/pagination)
    anchors = collect_anchors(main, url)
    classified = []
    for a in anchors:
        kind, pager = classify_anchor(a)
        a["kind"] = kind
        a["pager"] = pager
        classified.append(a)

    # collect readable text (allowed tags only)
    text = take_text(main, limit_chars=limit_text_chars)

    t_parse = (time.perf_counter() - t1) * 1000

    # stats
    total_chars = len(html)
    text_chars = len(text)
    a_total = len(classified)
    a_exhibitions = sum(1 for x in classified if x["kind"] == "exhibition")
    a_events = sum(1 for x in classified if x["kind"] == "event")
    a_pagers = sum(1 for x in classified if x["pager"])

    return {
        "url": url,
        "from_cache": from_cache,
        "stats": {
            "html_chars": total_chars,
            "text_chars": text_chars,
            "anchors_total": a_total,
            "anchors_exhibition": a_exhibitions,
            "anchors_event": a_events,
            "anchors_pagination": a_pagers,
            "t_fetch_ms": round(t_fetch,1),
            "t_condense_ms": round(t_parse,1),
            "t_total_ms": round(t_fetch + t_parse,1),
        },
        "text": text,
        "anchors": classified
    }

# ------------------------ CLI ------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python condense_exhibitions.py <museum_listing_url>")
        sys.exit(1)
    url = sys.argv[1]
    result = condense(url, limit_text_chars=16000)

    # Print timing & summary
    s = result["stats"]
    print("\n⏱️  Timing:")
    print(f"  Fetch:     {s['t_fetch_ms']:7.1f} ms (cache={result['from_cache']})")
    print(f"  Condense:  {s['t_condense_ms']:7.1f} ms")
    print(f"  TOTAL:     {s['t_total_ms']:7.1f} ms")
    print("\n📊 Size:")
    print(f"  HTML chars: {s['html_chars']:,}")
    print(f"  Text chars: {s['text_chars']:,}")

    print("\n🔗 Anchors:")
    print(f"  total={s['anchors_total']} | exhibitions≈{s['anchors_exhibition']} | events≈{s['anchors_event']} | pagination≈{s['anchors_pagination']}")

    # Save compact artifacts for LLM + planner
    out_base = Path("out")
    out_base.mkdir(exist_ok=True)
    base = sha1(url)[:8]
    (out_base / f"{base}_text.txt").write_text(result["text"], encoding="utf-8")
    (out_base / f"{base}_anchors.json").write_text(json.dumps(result["anchors"], indent=2, ensure_ascii=False), encoding="utf-8")
    (out_base / f"{base}_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ Saved:")
    print(f"  {out_base}/{base}_text.txt (LLM text input)")
    print(f"  {out_base}/{base}_anchors.json (href + context)")
    print(f"  {out_base}/{base}_summary.json (full summary)\n")

if __name__ == "__main__":
    main()
