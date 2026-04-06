#!/usr/bin/env python3
"""
bcscope_all.py - scrape in-scope domains from every public paying Bugcrowd program

usage:
    python bcscope_all.py                        # output all domains to stdout
    python bcscope_all.py -o ~/recon/all_scope/  # save per-program files to directory
    python bcscope_all.py --list                 # just list all programs, no scraping
"""
import asyncio
import sys
import json
import time
from pathlib import Path
import httpx

HEADERS = {
    "Accept": "application/vnd.bugcrowd.v4+json",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
}


async def fetch_programs(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all public bug bounty programs from Bugcrowd."""
    programs = []
    offset = 0
    limit = 24
    while True:
        try:
            r = await client.get(
                "https://bugcrowd.com/engagements.json",
                params={"offset": offset, "limit": limit},
                headers=HEADERS,
                timeout=20,
            )
            if r.status_code != 200:
                break
            data = r.json()
            batch = data.get("engagements", [])
            total = data.get("paginationMeta", {}).get("totalCount", 0)
            if not batch:
                break
            for p in batch:
                reward = p.get("rewardSummary", {}) or {}
                if reward.get("minReward") or reward.get("maxReward") or reward.get("summary"):
                    programs.append(p)
            print(f"[*] fetched offset {offset}/{total} — {len(programs)} paying programs so far", file=sys.stderr)
            if offset + limit >= total:
                break
            offset += limit
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[!] error fetching offset {offset}: {e}", file=sys.stderr)
            break
    return programs


async def scrape_scope(program_url: str, client: httpx.AsyncClient) -> list[str]:
    """Import and use bcscope's logic to get scope for one program."""
    from bcscope import try_api, normalize, extract_slug
    slug = extract_slug(program_url)
    targets = await try_api(slug, client)
    if targets:
        return normalize(targets)
    return []


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="scrape scope from all paying Bugcrowd programs")
    parser.add_argument("-o", "--output", default="", help="output directory (one file per program)")
    parser.add_argument("--list", action="store_true", help="list programs only, no scraping")
    parser.add_argument("--delay", type=float, default=1.0, help="delay between requests (default: 1.0s)")
    args = parser.parse_args()

    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        print("[*] fetching program list from Bugcrowd...", file=sys.stderr)
        programs = await fetch_programs(client)
        print(f"[*] found {len(programs)} paying programs", file=sys.stderr)

        if args.list:
            for p in programs:
                print(f"{p.get('name', '')} — https://bugcrowd.com{p.get('briefUrl', '')}")
            return

        if args.output:
            Path(args.output).mkdir(parents=True, exist_ok=True)

        all_domains = set()
        for i, p in enumerate(programs, 1):
            brief_url = p.get("briefUrl", "")
            name = p.get("name", brief_url)
            if not brief_url:
                continue
            slug = brief_url.strip("/").split("/")[-1]
            url = f"https://bugcrowd.com{brief_url}"
            print(f"[{i}/{len(programs)}] {name} ({slug})", file=sys.stderr)

            try:
                targets = await scrape_scope(url, client)
                if targets:
                    all_domains.update(targets)
                    if args.output:
                        out_file = Path(args.output) / f"{slug}.txt"
                        out_file.write_text("\n".join(targets) + "\n")
                        print(f"  -> {len(targets)} targets saved to {out_file}", file=sys.stderr)
                    else:
                        for t in targets:
                            print(t)
                else:
                    print(f"  -> no targets found", file=sys.stderr)
            except Exception as e:
                print(f"  -> error: {e}", file=sys.stderr)

            await asyncio.sleep(args.delay)

        print(f"\n[*] total unique domains: {len(all_domains)}", file=sys.stderr)
        if args.output:
            master = Path(args.output) / "_all_domains.txt"
            master.write_text("\n".join(sorted(all_domains)) + "\n")
            print(f"[*] master list saved to {master}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
