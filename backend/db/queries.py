"""
Common database queries.
"""

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import (
    Product,
    DemandData,
    SupplierMatch,
    Analysis,
    Verdict,
    PurchaseCapture,
    ListingObservation,
    QueryObservation,
    Sale,
    MonthlyStat,
)
from engine.listing_age import normalise_query
from scrapers.base import ScrapedProduct, DemandData as DemandDataDTO
from scrapers.browse_fields import (
    COMPARED,
    extract_observation,
    is_change,
)


def get_product_by_listing_id(db: Session, listing_id: str) -> Product | None:
    """Get product by eBay listing ID."""
    return db.query(Product).filter(Product.ebay_listing_id == listing_id).first()


def create_product(db: Session, **kwargs) -> Product:
    """Create a new product record."""
    product = Product(**kwargs)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def save_demand(db: Session, product_id: int, **kwargs) -> DemandData:
    """Save or update demand data for a product."""
    existing = db.query(DemandData).filter(DemandData.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    demand = DemandData(product_id=product_id, **kwargs)
    db.add(demand)
    db.commit()
    db.refresh(demand)
    return demand


def save_supplier_match(db: Session, product_id: int, **kwargs) -> SupplierMatch:
    """Save a supplier match for a product."""
    match = SupplierMatch(product_id=product_id, **kwargs)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def save_analysis(db: Session, product_id: int, **kwargs) -> Analysis:
    """Save or update LLM analysis for a product."""
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    analysis = Analysis(product_id=product_id, **kwargs)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def save_verdict(db: Session, product_id: int, **kwargs) -> Verdict:
    """Save or update verdict for a product."""
    existing = db.query(Verdict).filter(Verdict.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    verdict = Verdict(product_id=product_id, **kwargs)
    db.add(verdict)
    db.commit()
    db.refresh(verdict)
    return verdict


def get_recent_analyses(db: Session, limit: int = 20) -> list[dict]:
    """Get recent product analyses with verdicts."""
    results = (
        db.query(Product, Verdict)
        .join(Verdict, Verdict.product_id == Product.id)
        .order_by(Verdict.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": p.price,
            "verdict": v.verdict,
            "profit": v.profit_amount,
            "margin": v.profit_margin,
            "created_at": v.created_at.isoformat(),
        }
        for p, v in results
    ]


def is_data_fresh(db: Session, product_id: int, max_age_hours: int = 24) -> bool:
    """Check if product data is still fresh (reconcile pattern)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return False

    age = datetime.utcnow() - product.updated_at
    return age < timedelta(hours=max_age_hours)


def save_product(db: Session, product: ScrapedProduct) -> int:
    """Save a scraped product and return its ID."""
    existing = db.query(Product).filter(Product.ebay_url == product.url).first()
    if existing:
        existing.title = product.title
        existing.price = product.price
        existing.image_url = product.image_url
        existing.seller = product.seller
        existing.condition = product.condition
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing.id

    new_product = Product(
        ebay_url=product.url,
        title=product.title,
        price=product.price,
        image_url=product.image_url,
        seller=product.seller,
        condition=product.condition,
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product.id


def save_demand_data(db: Session, product_id: int, demand: DemandDataDTO) -> DemandData:
    """Save demand evidence from a scraped DemandData dataclass."""
    existing = db.query(DemandData).filter(DemandData.product_id == product_id).first()
    data = {
        "sold_count_30d": demand.sold_count_30d,
        "sold_count_7d": demand.sold_count_7d,
        "last_sale_date": demand.last_sale_date,
        "avg_sold_price": demand.avg_sold_price,
        "lowest_sold_price": demand.lowest_sold_price,
        "highest_sold_price": demand.highest_sold_price,
        "verified": demand.verified,
    }
    # A3 — the per-sale observations behind min/avg/max. Written whenever the
    # DTO carries the field (it now always does), including as [], because a
    # re-run that observed no sales must clear the previous run's chart
    # rather than keep redrawing it.
    if hasattr(demand, "sold_prices"):
        data["sold_prices"] = list(demand.sold_prices or [])
    # The SUPPLY-side set, written with the same all-or-nothing discipline: a
    # DTO that carries a field writes it, including as None or [], so a re-run
    # that observed nothing CLEARS the previous run instead of leaving stale
    # evidence on screen. Each of these is a declared column; none is inferred
    # from another, because a listing price and a sale price are not
    # interchangeable and must be stored apart.
    for _name in (
        "active_listings_in_band",
        "avg_active_price",
        "lowest_active_price",
        "highest_active_price",
        "active_prices",
    ):
        if hasattr(demand, _name):
            _value = getattr(demand, _name)
            data[_name] = list(_value or []) if _name.endswith("_prices") else _value
    # Phase C — the sold figure's provenance, with the invariant that makes it
    # worth storing: a source is a claim ABOUT a figure, so a row can never hold
    # a source with no figure. A re-run with no capture therefore CLEARS the
    # previous source rather than leaving "purchase history" attached to a NULL
    # count, which would read as a sold number that came from nowhere.
    sold_source = getattr(demand, "sold_source", None)
    sold_captured_at = getattr(demand, "sold_captured_at", None)
    if getattr(demand, "sold_count_7d", None) is None:
        sold_source = None
        sold_captured_at = None
    data["sold_source"] = sold_source
    data["sold_captured_at"] = sold_captured_at
    # P5/Phase C — only written when the DTO carries a source string (built by
    # the scraper, extended by analysis_pipeline) so the column default keeps
    # applying everywhere else.
    data_source = getattr(demand, "data_source", None)
    if data_source:
        data["data_source"] = data_source
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    demand_row = DemandData(product_id=product_id, **data)
    db.add(demand_row)
    db.commit()
    db.refresh(demand_row)
    return demand_row


def save_supplier_match_data(db: Session, product_id: int, supplier_data: dict) -> SupplierMatch:
    """Save a supplier match from a dict."""
    match = SupplierMatch(product_id=product_id, **supplier_data)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def save_analysis_data(db: Session, product_id: int, analysis: dict) -> Analysis:
    """Save or update LLM analysis from a dict."""
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing:
        for k, v in analysis.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    row = Analysis(product_id=product_id, **analysis)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def clear_analysis_data(db: Session, product_id: int) -> bool:
    """Remove the AI verdict stored for a product.

    Called when an analysis ran with NO AI behind it. `save_product` reuses
    the Product row for the same eBay URL and `save_analysis_data` only
    writes when it is called, so the row an earlier run left would be read
    by History as this run's verdict — an AI output for an analysis that
    produced none (C13). Returns True when a row was actually removed.
    """
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def save_verdict_data(db: Session, product_id: int, verdict: dict) -> Verdict:
    """Save or update verdict from a dict."""
    existing = db.query(Verdict).filter(Verdict.product_id == product_id).first()
    if existing:
        for k, v in verdict.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    row = Verdict(product_id=product_id, **verdict)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_recent_products(db: Session, limit: int = 20) -> list[dict]:
    """Get recent products with their verdicts."""
    results = (
        db.query(Product, Verdict)
        .outerjoin(Verdict, Verdict.product_id == Product.id)
        .order_by(Product.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": p.price,
            "url": p.ebay_url,
            "image_url": p.image_url,
            "verdict": v.verdict if v else None,
            "profit": v.profit_amount if v else None,
            "margin": v.profit_margin if v else None,
            "created_at": p.created_at.isoformat(),
        }
        for p, v in results
    ]


def get_product_by_url(db: Session, url: str) -> Product | None:
    """Check if a product URL has already been scraped."""
    return db.query(Product).filter(Product.ebay_url == url).first()


def is_data_fresh_by_product(db: Session, product_id: int, max_age_hours: int = 24) -> bool:
    """Check if product data is fresh enough to skip re-scraping."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return False
    age = datetime.utcnow() - product.updated_at
    return age < timedelta(hours=max_age_hours)


def get_latest_purchase_capture(db: Session, item_id: str) -> PurchaseCapture | None:
    """Most recent browser purchase-history capture for an eBay item (P5)."""
    return (
        db.query(PurchaseCapture)
        .filter(PurchaseCapture.item_id == str(item_id))
        .order_by(PurchaseCapture.captured_at.desc(), PurchaseCapture.id.desc())
        .first()
    )


def upsert_purchase_capture(
    db: Session,
    *,
    item_id: str,
    url: str | None,
    sold_7d: int,
    sold_30d: int | None,
    sales_json: str,
    captured_at: datetime,
    source: str = "extension",
) -> PurchaseCapture:
    """Insert or update the capture for `item_id` — latest capture wins.

    One row per item: the existing row's counts/sales/captured_at are
    replaced and any duplicate rows for the same item_id are removed.
    """
    item_id = str(item_id)
    existing = (
        db.query(PurchaseCapture)
        .filter(PurchaseCapture.item_id == item_id)
        .order_by(PurchaseCapture.captured_at.desc(), PurchaseCapture.id.desc())
        .all()
    )
    if existing:
        row = existing[0]
        for duplicate in existing[1:]:
            db.delete(duplicate)
        row.url = url
        row.sold_7d = sold_7d
        row.sold_30d = sold_30d
        row.sales_json = sales_json
        row.captured_at = captured_at
        row.source = source
    else:
        row = PurchaseCapture(
            item_id=item_id,
            url=url,
            sold_7d=sold_7d,
            sold_30d=sold_30d,
            sales_json=sales_json,
            captured_at=captured_at,
            source=source,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def purchase_capture_stats(db: Session, *, now: datetime | None = None) -> dict:
    """How much verified purchase-history data is actually stored.

    A read-only count for the extension popup, which shows it beside the
    extension's own local counter so a capture the popup *thought* it made can
    never be mistaken for a row that exists.

    The window is "last 24 hours" rather than "today" on purpose: captured_at
    is naive UTC and the person reading the popup is not, so a calendar day
    would be wrong by an hour and would read as a bug.
    """
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    last_capture_at = db.query(func.max(PurchaseCapture.captured_at)).scalar()
    return {
        "items_captured": int(db.query(func.count(PurchaseCapture.id)).scalar() or 0),
        "items_captured_24h": int(
            db.query(func.count(PurchaseCapture.id))
            .filter(PurchaseCapture.captured_at >= cutoff)
            .scalar()
            or 0
        ),
        "last_capture_at": last_capture_at.isoformat() if last_capture_at else None,
    }


def _reading_values(row: ListingObservation) -> dict:
    """The extractor's own field set, read back off a stored row.

    Driven by `browse_fields.COMPARED` rather than by a second hand-written
    list, so the comparison cannot drift from the columns: a field added to the
    extractor and not to the model raises here instead of silently never
    registering as a change.
    """
    return {name: getattr(row, name) for name in COMPARED}


def save_listing_observations(
    db: Session,
    readings: Iterable[tuple],
    *,
    observed_at: datetime | None = None,
) -> dict:
    """Store Browse readings, keeping only the ones that say something new.

    `readings` is an iterable of `(listing_id, payload, source)`. Append-only:
    nothing here is ever updated or deleted, because the value of the table is
    the sequence.

    Four outcomes, all counted, because a refresh should report what it actually
    recorded rather than imply that every card produced a row:

    * `recorded`  - differs from the last reading for that listing, so stored.
    * `unchanged` - repeats the last reading, so not stored again.
    * `duplicate` - the listing was already read earlier in THIS batch. Only the
      first is kept. MEASURED: the same listing came back from two different
      Browse queries in one refresh reporting `priorityListing` True in one and
      False in the other. Writing both put two rows in the table with the same
      `observed_at` contradicting each other - a change that never happened,
      since no time passed - and because each then differed from the latest row,
      every later refresh wrote two more, forever. Two readings taken at the
      same moment are one reading.
    * `empty`     - every field came back None. That payload was not a usable
      listing, and writing it would claim eBay reported nothing when in fact
      nothing was read (C1). Checked BEFORE the duplicate rule, so an
      unreadable report cannot shadow a readable one for the same listing.
    """
    stamped = observed_at or datetime.utcnow()
    recorded = unchanged = empty = duplicate = 0
    read_this_batch: set[str] = set()

    for listing_id, payload, source in readings:
        listing_id = str(listing_id)
        fields = extract_observation(payload)

        if not any(value is not None for value in fields.values()):
            empty += 1
            continue

        if listing_id in read_this_batch:
            duplicate += 1
            continue
        read_this_batch.add(listing_id)

        fields["source"] = source
        latest = (
            db.query(ListingObservation)
            .filter(ListingObservation.listing_id == listing_id)
            .order_by(
                ListingObservation.observed_at.desc(),
                ListingObservation.id.desc(),
            )
            .first()
        )
        if latest is not None and not is_change(_reading_values(latest), fields):
            unchanged += 1
            continue

        db.add(
            ListingObservation(listing_id=listing_id, observed_at=stamped, **fields)
        )
        recorded += 1

    db.commit()
    return {
        "readings": recorded + unchanged + empty + duplicate,
        "recorded": recorded,
        "unchanged": unchanged,
        "empty": empty,
        "duplicate": duplicate,
    }


def get_listing_observations(
    db: Session, listing_id: str, limit: int = 50
) -> list[ListingObservation]:
    """A listing's stored readings, newest first.

    `limit` bounds what a replay hands back; the sequence itself is never
    trimmed, so a deeper query is always possible later.
    """
    if not listing_id:
        return []
    return (
        db.query(ListingObservation)
        .filter(ListingObservation.listing_id == str(listing_id))
        .order_by(
            ListingObservation.observed_at.desc(), ListingObservation.id.desc()
        )
        .limit(limit)
        .all()
    )


def get_listing_observation_summary(db: Session, listing_id: str) -> dict:
    """What the age route needs from one listing's readings.

    `first_seen_at` is exact: the first stored reading for a listing is the
    first time this app saw it. `latest_reading_at` is not a last-seen time -
    a reading is stored only when something changed - so it is named for what
    it is. The creation date comes from the newest reading that actually
    carried one; a later summary that omitted the field must not erase a date
    an earlier reading did return.
    """
    if not listing_id:
        return {
            "readings": 0,
            "first_seen_at": None,
            "latest_reading_at": None,
            "item_creation_date": None,
        }
    rows = (
        db.query(ListingObservation)
        .filter(ListingObservation.listing_id == str(listing_id))
        .order_by(
            ListingObservation.observed_at.asc(), ListingObservation.id.asc()
        )
        .all()
    )
    if not rows:
        return {
            "readings": 0,
            "first_seen_at": None,
            "latest_reading_at": None,
            "item_creation_date": None,
        }
    creation = next(
        (
            row.item_creation_date
            for row in reversed(rows)
            if row.item_creation_date is not None
        ),
        None,
    )
    return {
        "readings": len(rows),
        "first_seen_at": rows[0].observed_at,
        "latest_reading_at": rows[-1].observed_at,
        "item_creation_date": creation,
    }


def get_seller_observations(
    db: Session,
    username: str,
    listing_ids: Iterable[str] | None = None,
) -> list[ListingObservation]:
    """Every stored reading for one seller, optionally limited to listings.

    Usernames are matched case-insensitively because eBay treats them that
    way; the stored spelling is returned to the caller rather than rewritten.
    `listing_ids` is applied in Python rather than as a SQL ``IN`` clause: a
    query lane can accumulate more than SQLite's parameter limit over time,
    and the number of readings for one seller is small enough not to need it.

    This reads observations that already exist. It writes nothing and spends
    no Browse call.
    """
    wanted = (username or "").strip()
    if not wanted:
        return []
    rows = (
        db.query(ListingObservation)
        .filter(func.lower(ListingObservation.seller_username) == wanted.lower())
        .order_by(
            ListingObservation.observed_at.asc(), ListingObservation.id.asc()
        )
        .all()
    )
    if listing_ids is not None:
        allowed = {str(listing_id) for listing_id in listing_ids if listing_id}
        rows = [row for row in rows if row.listing_id in allowed]
    return rows


def save_query_observations(db: Session, observations: Iterable[dict]) -> dict:
    """Store completed search result sets, one row per search.

    An observation with zero listings is stored: it is the difference between
    "this search returned nothing" and "this search never happened", and churn
    needs that difference. An observation with no query or no usable mapping
    is skipped and counted, because a row filed under a blank query lane
    cannot be compared with anything.
    """
    recorded = skipped = 0
    for observation in observations or []:
        if not isinstance(observation, dict):
            skipped += 1
            continue
        query = normalise_query(observation.get("query"))
        listings = observation.get("listings")
        if not query or not isinstance(listings, list):
            skipped += 1
            continue

        listings = [row for row in listings if isinstance(row, dict)]
        db.add(
            QueryObservation(
                query=query,
                observed_at=observation.get("observed_at") or datetime.utcnow(),
                source=observation.get("source") or "browse_search",
                price_filter=observation.get("filter"),
                sample_limit=observation.get("limit"),
                listing_count=len(listings),
                listings=listings,
            )
        )
        recorded += 1

    db.commit()
    return {"recorded": recorded, "skipped": skipped}


def get_query_observations(db: Session, query: str) -> list[QueryObservation]:
    """A query's stored search result sets, newest first.

    No limit: the churn report compares the latest set with every earlier one,
    so trimming here would silently hide an older last-seen date. The table
    grows by one row per analysis, not per listing.
    """
    key = normalise_query(query)
    if not key:
        return []
    return (
        db.query(QueryObservation)
        .filter(QueryObservation.query == key)
        .order_by(
            QueryObservation.observed_at.desc(), QueryObservation.id.desc()
        )
        .all()
    )


# --- Phase I: user-declared sales and monthly stats ------------------------


def sale_money(
    *,
    sale_price: float | None,
    supplier_cost: float | None,
    shipping_cost: float | None,
    ebay_fees: float | None,
    quantity: int | None,
) -> tuple[float | None, float | None]:
    """Profit and margin for one declared sale, or ``(None, None)``.

    All three costs must be declared. A missing cost is not a zero: treating
    it as one would silently overstate profit (C1), so the pair stays absent
    and the caller reports why. The values are per unit and multiplied by the
    declared quantity, matching how the sale form describes them.
    """
    if sale_price is None or quantity is None or quantity <= 0:
        return None, None
    if (
        supplier_cost is None
        or shipping_cost is None
        or ebay_fees is None
    ):
        return None, None

    revenue = sale_price * quantity
    costs = (supplier_cost + shipping_cost + ebay_fees) * quantity
    profit = round(revenue - costs, 2)
    margin = round(profit / revenue * 100, 2) if revenue > 0 else None
    return profit, margin


def sale_to_dict(sale: Sale) -> dict:
    """One sale as the API and exports present it."""
    complete = sale.profit is not None and sale.margin_percent is not None
    return {
        "id": sale.id,
        "product_name": sale.product_name,
        "category": sale.category or "",
        "sale_price": sale.sale_price,
        "supplier_cost": sale.supplier_cost,
        "shipping_cost": sale.shipping_cost,
        "ebay_fees": sale.ebay_fees,
        "profit": sale.profit,
        "margin_percent": sale.margin_percent,
        "quantity": sale.quantity,
        "sale_date": sale.sale_date.date().isoformat() if sale.sale_date else None,
        "buyer_location": sale.buyer_location or "",
        "notes": sale.notes or "",
        "created_at": (
            sale.created_at.isoformat() if sale.created_at else None
        ),
        "user_declared": True,
        "profit_is_complete": complete,
        "profit_missing_reason": (
            None
            if complete
            else (
                "Profit is not shown for this sale because at least one cost "
                "was not declared."
            )
        ),
    }


def list_sales(db: Session, limit: int = 100, offset: int = 0) -> list[Sale]:
    """Newest sales first, with a bounded page."""
    return (
        db.query(Sale)
        .order_by(Sale.sale_date.desc(), Sale.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_sales(db: Session) -> int:
    return int(db.query(func.count(Sale.id)).scalar() or 0)


def get_sale(db: Session, sale_id: int) -> Sale | None:
    return db.query(Sale).filter(Sale.id == sale_id).first()


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end_year = year + (1 if month == 12 else 0)
    end_month = 1 if month == 12 else month + 1
    return start, datetime(end_year, end_month, 1)


def recompute_monthly_stats(
    db: Session,
    months: Iterable[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Rebuild `monthly_stats` rows from the sales they summarise.

    Called on every sale write, so the table can never drift from the rows it
    describes. Passing a month whose last sale was just deleted removes that
    month's row rather than leaving a stale total behind.

    A month holding any sale with an undeclared cost gets ``total_profit =
    None`` and ``avg_margin = None``. Revenue, sale count and units are still
    measured; profit is the only value that needs all the costs.
    """
    if months is None:
        pairs = {
            (row.sale_date.year, row.sale_date.month)
            for row in db.query(Sale).all()
            if row.sale_date is not None
        }
    else:
        pairs = {(int(year), int(month)) for year, month in months}

    touched: list[tuple[int, int]] = []
    for year, month in sorted(pairs):
        start, end = _month_bounds(year, month)
        sales = (
            db.query(Sale)
            .filter(Sale.sale_date >= start, Sale.sale_date < end)
            .all()
        )
        existing = (
            db.query(MonthlyStat)
            .filter(MonthlyStat.year == year, MonthlyStat.month == month)
            .order_by(MonthlyStat.id)
            .all()
        )

        if not sales:
            for row in existing:
                db.delete(row)
            touched.append((year, month))
            continue

        revenue = round(
            sum(sale.sale_price * (sale.quantity or 0) for sale in sales),
            2,
        )
        complete = all(sale.profit is not None for sale in sales)
        profit = round(sum(sale.profit for sale in sales), 2) if complete else None
        margin = (
            round(profit / revenue * 100, 2)
            if complete and profit is not None and revenue > 0
            else None
        )
        total_sales = len(sales)

        if existing:
            row = existing[0]
            for duplicate in existing[1:]:
                db.delete(duplicate)
        else:
            row = MonthlyStat(year=year, month=month)
            db.add(row)
        row.total_revenue = revenue
        row.total_profit = profit
        row.total_sales = total_sales
        row.avg_margin = margin
        row.updated_at = datetime.utcnow()
        touched.append((year, month))

    db.commit()
    return touched


def create_sale_record(
    db: Session,
    *,
    product_name: str,
    sale_price: float,
    supplier_cost: float,
    shipping_cost: float,
    ebay_fees: float,
    quantity: int,
    sale_date: datetime,
    category: str = "",
    buyer_location: str = "",
    notes: str = "",
) -> Sale:
    profit, margin = sale_money(
        sale_price=sale_price,
        supplier_cost=supplier_cost,
        shipping_cost=shipping_cost,
        ebay_fees=ebay_fees,
        quantity=quantity,
    )
    sale = Sale(
        product_name=product_name,
        category=category,
        sale_price=sale_price,
        supplier_cost=supplier_cost,
        shipping_cost=shipping_cost,
        ebay_fees=ebay_fees,
        profit=profit,
        margin_percent=margin,
        quantity=quantity,
        sale_date=sale_date,
        buyer_location=buyer_location,
        notes=notes,
    )
    db.add(sale)
    db.flush()
    recompute_monthly_stats(db, [(sale_date.year, sale_date.month)])
    db.refresh(sale)
    return sale


def update_sale_record(db: Session, sale: Sale, **fields) -> Sale:
    old_pair = (sale.sale_date.year, sale.sale_date.month)
    for key, value in fields.items():
        setattr(sale, key, value)
    sale.profit, sale.margin_percent = sale_money(
        sale_price=sale.sale_price,
        supplier_cost=sale.supplier_cost,
        shipping_cost=sale.shipping_cost,
        ebay_fees=sale.ebay_fees,
        quantity=sale.quantity,
    )
    db.flush()
    new_pair = (sale.sale_date.year, sale.sale_date.month)
    recompute_monthly_stats(db, {old_pair, new_pair})
    db.refresh(sale)
    return sale


def delete_sale_record(db: Session, sale: Sale) -> None:
    pair = (sale.sale_date.year, sale.sale_date.month)
    db.delete(sale)
    db.flush()
    recompute_monthly_stats(db, [pair])
