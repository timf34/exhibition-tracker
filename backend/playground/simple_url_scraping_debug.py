#!/usr/bin/env python3
"""
Simple URL debugging script to test different methods of fetching HTML
"""
import requests
from urllib.parse import urlparse
import time

def test_url_methods(url):
    """Test various methods to fetch a URL"""
    print(f"\n{'='*60}")
    print(f"Testing URL: {url}")
    print('='*60)
    
    # Method 1: Basic requests
    print("\n1. Basic requests.get():")
    try:
        resp = requests.get(url, timeout=10)
        print(f"   ✅ Status: {resp.status_code}")
        print(f"   Headers: {dict(list(resp.headers.items())[:5])}...")
        print(f"   Content length: {len(resp.text)} chars")
        print(f"   First 200 chars: {resp.text[:200]}...")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Method 2: With browser-like headers
    print("\n2. Requests with browser headers:")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"   ✅ Status: {resp.status_code}")
        print(f"   Content length: {len(resp.text)} chars")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Method 3: With session (maintains cookies)
    print("\n3. Requests with session:")
    try:
        session = requests.Session()
        session.headers.update(headers)
        resp = session.get(url, timeout=15)
        print(f"   ✅ Status: {resp.status_code}")
        print(f"   Cookies: {session.cookies.get_dict()}")
        print(f"   Content length: {len(resp.text)} chars")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Method 4: Check with curl command (if available)
    print("\n4. Testing with curl command:")
    import subprocess
    try:
        result = subprocess.run(
            ['curl', '-I', '-s', '-L', '--max-time', '10', url],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("   ✅ Curl headers:")
            print("   " + "\n   ".join(result.stdout.split('\n')[:5]))
    except FileNotFoundError:
        print("   ⚠️ curl not available")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Method 5: Try HTTP/1.1 instead of HTTP/2
    print("\n5. Force HTTP/1.1:")
    try:
        import httpx
        client = httpx.Client(http2=False, follow_redirects=True)
        resp = client.get(url, timeout=15, headers=headers)
        print(f"   ✅ Status: {resp.status_code}")
        print(f"   HTTP version: {resp.http_version}")
        print(f"   Content length: {len(resp.text)} chars")
    except ImportError:
        print("   ⚠️ httpx not installed (pip install httpx)")
    except Exception as e:
        print(f"   ❌ Failed: {e}")

# Test URLs
test_urls = [
    "https://www.fondationlouisvuitton.fr/en/programme",
    # Add more problematic URLs here
]

if __name__ == "__main__":
    for url in test_urls:
        test_url_methods(url)
        time.sleep(1)  # Be polite between tests