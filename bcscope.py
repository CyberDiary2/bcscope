#!/usr/bin/env python3
"""
bcscope - Bugcrowd in-scope URL scraper
usage: python bcscope.py <program_url> [-o output.txt]

examples:
    python bcscope.py https://bugcrowd.com/tesla
    python bcscope.py https://bugcrowd.com/tesla -o tesla_scope.txt
    python bcscope.py https://bugcrowd.com/tesla | dreakon scan -
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx


SCOPE_API_HEADERS = {
    "Accept": "application/vnd.bugcrowd.v4+json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
}


def extract_slug(url: str) -> str:
    """Extract program slug from a Bugcrowd URL."""
    url = url.rstrip("/")
    return url.split("/")[-1]


async def try_api(slug: str, client: httpx.AsyncClient) -> list[str]:
    """Try Bugcrowd's JSON API endpoints for scope data."""
    endpoints = [
        f"https://bugcrowd.com/{slug}/target_groups",
        f"https://bugcrowd.com/engagements/{slug}/scope",
        f"https://bugcrowd.com/programs/{slug}/scope.json",
    ]
    for url in endpoints:
        try:
            r = await client.get(url, headers=SCOPE_API_HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                targets = extract_from_json(data)
                if targets:
                    return targets
        except Exception:
            continue
    return []


def extract_from_json(data: dict | list) -> list[str]:
    """Recursively extract target URLs/domains from JSON response."""
    targets = []

    def walk(obj):
        if isinstance(obj, dict):
            # Common Bugcrowd API field names for targets
            for key in ("target", "name", "uri", "domain", "url", "host"):
                val = obj.get(key)
                if val and isinstance(val, str) and looks_like_target(val):
                    targets.append(val.strip())
            # Check in_scope flag
            if obj.get("in_scope") is False:
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return sorted(set(targets))


def looks_like_target(val: str) -> bool:
    """Filter out noise - keep domains, wildcards, and URLs."""
    val = val.strip()
    if not val or len(val) < 3 or len(val) > 253:
        return False
    # Accept wildcards, domains, URLs
    if val.startswith(("http://", "https://", "*.", "www.")):
        return True
    # Accept bare domains (at least one dot, no spaces)
    if "." in val and " " not in val and "/" not in val:
        return True
    return False


async def try_playwright(url: str) -> list[str]:
    """Use Playwright to render the page and extract scope targets."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[!] playwright not installed - run: pip install playwright && playwright install chromium", file=sys.stderr)
        return []

    targets = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Intercept API responses for scope data
        api_data = []

        async def handle_response(response):
            if "target_group" in response.url or "scope" in response.url or "target" in response.url:
                try:
                    body = await response.json()
                    api_data.append(body)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # Try to extract from intercepted API calls first
            for data in api_data:
                found = extract_from_json(data)
                targets.extend(found)

            if not targets:
                # Fall back to scraping the DOM
                # Look for scope table rows
                rows = await page.query_selector_all("[data-target-name], [data-target], .bc-target-name, .scope-target")
                for row in rows:
                    text = await row.inner_text()
                    text = text.strip()
                    if looks_like_target(text):
                        targets.append(text)

            if not targets:
                # Try extracting from page JSON data embedded in script tags
                content = await page.content()
                json_blobs = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', content, re.DOTALL)
                for blob in json_blobs:
                    try:
                        data = json.loads(blob)
                        found = extract_from_json(data)
                        targets.extend(found)
                    except Exception:
                        pass

                # Also try window.__REDUX_STATE__ or similar
                state_matches = re.findall(r'window\.__(?:STATE|DATA|STORE|REDUX_STATE)__\s*=\s*({.*?});', content, re.DOTALL)
                for match in state_matches:
                    try:
                        data = json.loads(match)
                        found = extract_from_json(data)
                        targets.extend(found)
                    except Exception:
                        pass

        except Exception as e:
            print(f"[!] page load error: {e}", file=sys.stderr)
        finally:
            await browser.close()

    return sorted(set(targets))


async def scrape(program_url: str, output: str = "") -> list[str]:
    slug = extract_slug(program_url)
    print(f"[*] scraping scope for: {slug}", file=sys.stderr)

    # Try API first (faster)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        targets = await try_api(slug, client)

    if targets:
        print(f"[*] found {len(targets)} targets via API", file=sys.stderr)
    else:
        print(f"[*] API failed, trying playwright...", file=sys.stderr)
        targets = await try_playwright(program_url)
        print(f"[*] found {len(targets)} targets via playwright", file=sys.stderr)

    if not targets:
        print("[!] no targets found - program may require login or have no public scope", file=sys.stderr)
        return []

    # Write output
    if output:
        Path(output).write_text("\n".join(targets) + "\n")
        print(f"[*] saved to {output}", file=sys.stderr)
    else:
        for t in targets:
            print(t)

    return targets


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="scrape in-scope URLs from a public Bugcrowd program",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python bcscope.py https://bugcrowd.com/tesla
  python bcscope.py https://bugcrowd.com/tesla -o tesla_scope.txt
  python bcscope.py https://bugcrowd.com/tesla -o scope.txt && dreakon scan tesla.com -i scope.txt
        """,
    )
    parser.add_argument("url", help="Bugcrowd program URL (e.g. https://bugcrowd.com/tesla)")
    parser.add_argument("-o", "--output", default="", help="output file (default: stdout)")
    args = parser.parse_args()

    asyncio.run(scrape(args.url, args.output))


if __name__ == "__main__":
    main()
