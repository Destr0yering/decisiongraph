"""Seed the two governed retail datasets used by the DecisionGraph demo."""

import os
from pathlib import Path
import sqlite3

from datahub.sdk import DataHubClient, Dataset


def main() -> None:
    if not os.getenv("DATAHUB_GMS_URL"):
        os.environ["DATAHUB_GMS_URL"] = "http://localhost:8080"

    revision = os.getenv("DECISIONGRAPH_DEMO_REVISION", "1")
    updated = revision == "2"
    candidate_count = "4" if updated else "3"
    snapshot_date = "2026-07-29" if updated else "2026-07-26"
    generated_date = "2026-07-29" if updated else "2026-07-26"

    client = DataHubClient.from_env()
    datasets = [
        Dataset(
            platform="demo",
            name="fiction_retail.inventory",
            display_name="Fiction Retail Inventory",
            description=(
                "Current Northeast inventory snapshot. "
                f"{'Four' if updated else 'Three'} governed reorder candidates "
                "are below forecast demand: SKU-DG-101 has 60 units on hand, "
                "SKU-DG-102 has 45, SKU-DG-103 has 30"
                f"{', and SKU-DG-104 has 55' if updated else ''}. Snapshot "
                f"freshness is FRESH as of {snapshot_date}."
            ),
            custom_properties={
                "region": "Northeast",
                "snapshot_date": snapshot_date,
                "freshness_status": "FRESH",
                "reorder_candidates": candidate_count,
            },
            schema=[
                ("product_id", "varchar(32)", "Governed product identifier"),
                ("region", "varchar(32)", "Inventory region"),
                ("on_hand_units", "integer", "Current units available"),
                ("reorder_point", "integer", "Minimum desired stock level"),
                ("snapshot_date", "date", "Inventory snapshot date"),
            ],
        ),
        Dataset(
            platform="demo",
            name="fiction_retail.northeast_forecast",
            display_name="Northeast Demand Forecast",
            description=(
                "Thirty-day Northeast demand forecast. SKU-DG-101 forecasts "
                "140 units, SKU-DG-102 forecasts 115, and SKU-DG-103 forecasts "
                "92"
                f"{', while SKU-DG-104 forecasts 130' if updated else ''}, "
                "exceeding the corresponding on-hand inventory snapshot."
            ),
            custom_properties={
                "region": "Northeast",
                "forecast_horizon_days": "30",
                "generated_date": generated_date,
                "model_status": "APPROVED",
            },
            schema=[
                ("product_id", "varchar(32)", "Governed product identifier"),
                ("region", "varchar(32)", "Forecast region"),
                (
                    "forecast_units",
                    "integer",
                    "Expected demand over the forecast horizon",
                ),
                (
                    "forecast_horizon_days",
                    "integer",
                    "Number of days covered by the forecast",
                ),
                ("generated_date", "date", "Forecast generation date"),
            ],
        ),
    ]

    for dataset in datasets:
        client.entities.upsert(dataset)
        print(f"Seeded {dataset.urn}")

    analytics_db = os.getenv("DECISIONGRAPH_ANALYTICS_DB_PATH")
    if analytics_db:
        path = Path(analytics_db)
        with sqlite3.connect(path) as connection:
            if updated:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO inventory
                    (product_id, region, on_hand_units, reorder_point, snapshot_date)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("SKU-DG-104", "Northeast", 55, 95, snapshot_date),
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO northeast_forecast
                    (product_id, region, forecast_units, forecast_horizon_days,
                     generated_date)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("SKU-DG-104", "Northeast", 130, 30, generated_date),
                )
            else:
                connection.execute(
                    "DELETE FROM inventory WHERE product_id = ?",
                    ("SKU-DG-104",),
                )
                connection.execute(
                    "DELETE FROM northeast_forecast WHERE product_id = ?",
                    ("SKU-DG-104",),
                )
        print(f"Updated analytics fixture {path} to revision {revision}")


if __name__ == "__main__":
    main()
