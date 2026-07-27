"""Seed the two governed retail datasets used by the DecisionGraph demo."""

import os

from datahub.sdk import DataHubClient, Dataset


def main() -> None:
    if not os.getenv("DATAHUB_GMS_URL"):
        os.environ["DATAHUB_GMS_URL"] = "http://localhost:8080"

    client = DataHubClient.from_env()
    datasets = [
        Dataset(
            platform="demo",
            name="fiction_retail.inventory",
            display_name="Fiction Retail Inventory",
            description=(
                "Current Northeast inventory snapshot. Three governed reorder "
                "candidates are below forecast demand: SKU-DG-101 has 60 units "
                "on hand, SKU-DG-102 has 45, and SKU-DG-103 has 30. Snapshot "
                "freshness is FRESH as of 2026-07-26."
            ),
            custom_properties={
                "region": "Northeast",
                "snapshot_date": "2026-07-26",
                "freshness_status": "FRESH",
                "reorder_candidates": "3",
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
                "92, exceeding the corresponding on-hand inventory snapshot."
            ),
            custom_properties={
                "region": "Northeast",
                "forecast_horizon_days": "30",
                "generated_date": "2026-07-26",
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


if __name__ == "__main__":
    main()
