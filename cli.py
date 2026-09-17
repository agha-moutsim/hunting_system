"""
CLI tool for quick testing without the web dashboard.

Usage:
    python cli.py search "wireless earbuds"
    python cli.py analyze "wireless earbuds"
    python cli.py profit 15.99 8.50
    python cli.py suppliers
    python cli.py status
"""

import asyncio
import json
import sys
from datetime import datetime

import click

from config import FILTERS, PROFIT_CONFIG

# Force UTF-8 output on Windows consoles (avoids cp1252 UnicodeEncodeError)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


@click.group()
def cli():
    """eBay Hunter — Product Sourcing CLI"""
    pass


@cli.command()
@click.argument("query")
@click.option("--limit", "-n", default=5, help="Number of results")
def search(query: str, limit: int):
    """Search eBay UK for a product."""
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    try:
        results = scraper.search(query, limit=limit)
        if not results:
            click.echo("No results found. Check if eBay API keys are set in .env")
            return

        click.echo(f"\nFound {len(results)} results for '{query}':\n")
        for i, p in enumerate(results, 1):
            click.echo(f"{i}. {p.title[:70]}")
            click.echo(f"   Price: £{p.price:.2f}")
            click.echo(f"   URL: {p.url}")
            click.echo()
    finally:
        scraper.close()


@cli.command()
@click.argument("query")
def analyze(query: str):
    """Run full analysis on a product."""
    from pipeline import Pipeline

    click.echo(f"\nAnalyzing: {query}\n")
    click.echo("Running pipeline...")

    pipeline = Pipeline()
    result = asyncio.run(pipeline.run(query))

    # Print scorecard
    if result.get("scorecard"):
        click.echo("\n" + result["scorecard"])

    # Print errors
    if result.get("errors"):
        click.echo("\nErrors:")
        for err in result["errors"]:
            click.echo(f"  - {err}")


@cli.command()
@click.argument("ebay_price", type=float)
@click.argument("supplier_price", type=float)
def profit(ebay_price: float, supplier_price: float):
    """Calculate profit for a product."""
    from engine.profit import calculate_profit

    result = calculate_profit(ebay_price, supplier_price)

    click.echo(f"\nProfit Calculation:")
    click.echo(f"  eBay Price:      £{ebay_price:.2f}")
    click.echo(f"  Supplier Price:  £{supplier_price:.2f}")
    click.echo(f"  eBay Fee (12.8%): £{result['ebay_fee']:.2f}")
    click.echo(f"  Returns Buffer (3%): £{result['returns_buffer']:.2f}")
    click.echo(f"  ─────────────────")
    click.echo(f"  Profit:          £{result['profit']:.2f}")
    click.echo(f"  Margin:          {result['margin']:.1f}%")

    if result["profit"] > 0:
        click.echo(f"\n  ✓ PROFITABLE")
    else:
        click.echo(f"\n  ✗ NOT PROFITABLE")


@cli.command()
def suppliers():
    """List all configured suppliers."""
    import json

    with open("suppliers.json") as f:
        data = json.load(f)

    click.echo(f"\nConfigured Suppliers ({len(data['suppliers'])}):\n")
    for s in data["suppliers"]:
        click.echo(f"  {s['name']}")
        click.echo(f"    Type: {s['type']}")
        click.echo(f"    URL: {s['base_url']}")
        click.echo(f"    Delivery: {s['delivery_days_min']}-{s['delivery_days_max']} days")
        click.echo()


@cli.command()
def status():
    """Check system status."""
    from sqlalchemy import text
    from db.database import SessionLocal

    click.echo("\nSystem Status:\n")

    # Database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        click.echo("  Database:     ✓ Connected")
    except Exception as e:
        click.echo(f"  Database:     ✗ {e}")

    # Ollama
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            click.echo("  Ollama:       ✓ Online")
        else:
            click.echo("  Ollama:       ✗ Not responding")
    except Exception:
        click.echo("  Ollama:       ✗ Offline")

    # eBay API
    from config import EBAY_CLIENT_ID, EBAY_ENVIRONMENT
    if EBAY_CLIENT_ID:
        click.echo(f"  eBay API:     ✓ Configured ({EBAY_ENVIRONMENT})")
    else:
        click.echo("  eBay API:     ✗ Not configured (add to .env)")

    click.echo()


@cli.command()
@click.argument("title")
@click.option("--price", "-p", type=float, required=True, help="Product price")
@click.option("--condition", "-c", default="New", help="Product condition")
def manual(title: str, price: float, condition: str):
    """Add a product manually (skip eBay scraping)."""
    from pipeline import Pipeline

    click.echo(f"\nManual product entry:")
    click.echo(f"  Title: {title}")
    click.echo(f"  Price: £{price:.2f}")
    click.echo(f"  Condition: {condition}")
    click.echo()

    pipeline = Pipeline()
    result = asyncio.run(pipeline.run_manual(title, price, condition))

    if result.get("scorecard"):
        click.echo(result["scorecard"])


if __name__ == "__main__":
    cli()
