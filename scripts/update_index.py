import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isss_bot import config, db
from isss_bot.crawl import CrawlReport, crawl
from isss_bot.index import IndexReport, index

VOYAGE_PRICES_PER_MILLION_TOKENS = {"voyage-4-large": 0.12, "voyage-4": 0.06, "voyage-4-lite": 0.02}


def print_crawl_report(report: CrawlReport, seconds: float) -> None:
    counts = ", ".join(f"{len(urls)} {outcome}" for outcome, urls in report.outcomes.items())
    print(f"\nCrawl finished in {seconds:.0f}s: {counts}, {len(report.errors)} errors, {len(report.skipped)} skipped")
    if report.link_kinds:
        kinds = ", ".join(f"{kind} {count}" for kind, count in report.link_kinds.most_common())
        print(f"Links by kind: {kinds}")
    for url in report.outcomes["gone"]:
        print(f"  gone     {url}")
    for url, reason in report.skipped:
        print(f"  skipped  {url}: {reason}")
    for url, error in report.errors:
        print(f"  error    {url}: {error}")


def print_index_report(report: IndexReport, seconds: float) -> None:
    price = VOYAGE_PRICES_PER_MILLION_TOKENS.get(config.VOYAGE_MODEL)
    cost = f", about ${report.tokens_embedded * price / 1_000_000:.4f}" if price else ""
    print(
        f"\nIndex finished in {seconds:.0f}s with {config.VOYAGE_MODEL}: {report.pages_indexed} pages re-indexed, "
        f"{report.chunks_written} chunks written, {report.chunks_removed} removed, "
        f"{report.tokens_embedded} tokens embedded{cost}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl the ISSS website and update the search index.")
    parser.add_argument("command", choices=["crawl", "index", "all"])
    args = parser.parse_args()

    db.create_schema()
    exit_code = 0
    with db.connect() as conn:
        if args.command in ("crawl", "all"):
            started = time.monotonic()
            crawl_report = crawl(conn)
            print_crawl_report(crawl_report, time.monotonic() - started)
            exit_code = 1 if crawl_report.errors else 0
        if args.command in ("index", "all"):
            started = time.monotonic()
            print_index_report(index(conn), time.monotonic() - started)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
