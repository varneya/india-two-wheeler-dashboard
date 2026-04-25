"""
Seed data:
 - Legacy XSR 155 sales rows (kept for the original-product-launch demo).
 - Catalogue bikes — every bike in `bike_catalogue.CATALOGUE` gets a `bikes`
   table row at startup, so even bikes that haven't been scraped yet are
   pickable in the UI (otherwise gating logic that relies on /api/bikes
   silently breaks for catalogue-only models like Kawasaki Ninja).
"""

import database
import bike_catalogue

LEGACY_BIKE = {
    "id": "yamaha-xsr-155",
    "brand": "Yamaha",
    "model": "XSR 155",
    "display_name": "Yamaha XSR 155",
    "keywords": ["XSR 155", "XSR"],
    "bikewale_slug": "yamaha-bikes/xsr-155",
    "launch_month": "2025-11",
}

LEGACY_SALES = [
    {
        "month": "2025-11",
        "units_sold": 16359,
        "source_url": "https://www.bikedekho.com/news/yamaha-xsr-155-now-the-best-selling-yamaha-bike-in-india-18959",
    },
    {
        "month": "2025-12",
        "units_sold": 14951,
        "source_url": "https://www.rushlane.com/yamaha-sales-breakup-dec-2025-xsr155-becomes-top-seller-12538808.html",
    },
]


def seed_catalogue_bikes() -> int:
    """Ensure every bike in the catalogue has a row in the `bikes` table.
    Returns the number of new rows inserted (existing rows are left intact —
    `upsert_bike` preserves bikewale_ok/launch_month if already set)."""
    inserted = 0
    for brand_id, models in bike_catalogue.CATALOGUE.items():
        brand_display = bike_catalogue.BRANDS[brand_id]["display"]
        for entry in models:
            bike_id = bike_catalogue.make_bike_id(brand_id, entry["canonical"])
            existing = database.get_bike(bike_id)
            if existing is None:
                inserted += 1
            database.upsert_bike(
                bike_id=bike_id,
                brand=brand_display,
                model=entry["canonical"],
                display_name=f"{brand_display} {entry['canonical']}",
                keywords=entry.get("keywords") or [entry["canonical"]],
                bikewale_slug=entry.get("bikewale"),
                launch_month=None,  # let discovery fill this in
            )
            # Trust the catalogue-supplied BikeWale slug — we curated it
            if entry.get("bikewale") and not (existing and existing.get("bikewale_ok")):
                database.set_bikewale_ok(bike_id, True, slug=entry["bikewale"])
    if inserted:
        print(f"[seed] added {inserted} catalogue bike rows")
    return inserted


def seed_if_empty():
    # 1. Legacy XSR 155 demo data (only on a fresh DB)
    bike = database.get_bike(LEGACY_BIKE["id"])
    if bike is None:
        database.upsert_bike(
            bike_id=LEGACY_BIKE["id"],
            brand=LEGACY_BIKE["brand"],
            model=LEGACY_BIKE["model"],
            display_name=LEGACY_BIKE["display_name"],
            keywords=LEGACY_BIKE["keywords"],
            bikewale_slug=LEGACY_BIKE["bikewale_slug"],
            launch_month=LEGACY_BIKE["launch_month"],
        )
        database.set_bikewale_ok(LEGACY_BIKE["id"], True)

    if not database.get_all_sales(bike_id=LEGACY_BIKE["id"]):
        for entry in LEGACY_SALES:
            database.upsert_sale(
                bike_id=LEGACY_BIKE["id"],
                month=entry["month"],
                units_sold=entry["units_sold"],
                source_url=entry["source_url"],
            )

    # 2. Always: ensure all catalogue bikes have a row, so /api/bikes returns
    #    everything pickable in the UI (including not-yet-scraped models).
    seed_catalogue_bikes()
