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
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

console = Console()

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
        results_table = Table(
            "program", "slug", "targets", "sample",
            title="bugcrowd scope scraper",
            show_lines=False,
        )
        results_table.columns[0].style = "bold cyan"
        results_table.columns[2].style = "green"

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("scraping...", total=len(programs))

            for i, p in enumerate(programs, 1):
                brief_url = p.get("briefUrl", "")
                name = p.get("name", brief_url)
                if not brief_url:
                    progress.advance(task)
                    continue
                slug = brief_url.strip("/").split("/")[-1]
                url = f"https://bugcrowd.com{brief_url}"
                progress.update(task, description=f"[{i}/{len(programs)}] {name[:40]}")

                try:
                    targets = await scrape_scope(url, client)
                    if targets:
                        all_domains.update(targets)
                        sample = targets[0] if targets else ""
                        results_table.add_row(name[:40], slug, str(len(targets)), sample)
                        if args.output:
                            out_file = Path(args.output) / f"{slug}.txt"
                            out_file.write_text("\n".join(targets) + "\n")
                        else:
                            for t in targets:
                                print(t)
                    else:
                        results_table.add_row(name[:40], slug, "[dim]0[/dim]", "[dim]no targets[/dim]")
                except Exception as e:
                    results_table.add_row(name[:40], slug, "[red]err[/red]", str(e)[:40])

                progress.advance(task)
                await asyncio.sleep(args.delay)

        console.print(results_table)
        console.print(f"\n[bold green]total unique domains: {len(all_domains)}[/bold green]")
        if args.output:
            master = Path(args.output) / "_all_domains.txt"
            master.write_text("\n".join(sorted(all_domains)) + "\n")
            console.print(f"[dim]master list saved to {master}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
