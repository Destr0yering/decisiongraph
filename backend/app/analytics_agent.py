"""Provider-neutral client for DataHub's open-source Analytics Agent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import DecisionContext, ReorderAnalysis


REORDER_SQL = (
    "SELECT i.product_id, i.on_hand_units, f.forecast_units, "
    "f.forecast_units - i.on_hand_units AS recommended_reorder_quantity "
    "FROM inventory AS i JOIN northeast_forecast AS f "
    "ON i.product_id = f.product_id AND i.region = f.region "
    "WHERE i.region = 'Northeast' "
    "AND f.forecast_units > i.on_hand_units"
)

REORDER_QUESTION = (
    "Using only the governed Fiction Retail inventory and Northeast forecast "
    "datasets, identify products whose forecast demand exceeds on-hand "
    "inventory. Return the product_id, on_hand_units, forecast_units, and "
    "recommended_reorder_quantity. Include the SQL and a chart. In the "
    "configured SQL engine, the governed DataHub datasets are mapped to the "
    "exact SQLite table names inventory and northeast_forecast. Use "
    "execute_sql exactly once with this governed query, without adding any "
    f"columns or conditions: {REORDER_SQL}. Do not infer or invent rows if "
    "SQL execution fails. DecisionGraph already verified the DataHub context, "
    "so do not call additional catalog or business-context search tools."
)

REORDER_COLUMNS = {
    "product_id",
    "on_hand_units",
    "forecast_units",
    "recommended_reorder_quantity",
}


def _canonical_sql(value: object) -> str:
    return " ".join(str(value).strip().rstrip(";").split()).casefold()


def _validate_reorder_result(
    sql: object, rows: object, events: list[dict[str, object]]
) -> list[dict[str, object]]:
    if _canonical_sql(sql) != _canonical_sql(REORDER_SQL):
        raise AnalyticsUnavailable(
            "Analytics Agent did not execute the governed reorder SQL exactly"
        )
    if not any(event.get("event") == "COMPLETE" for event in events):
        raise AnalyticsUnavailable(
            "Analytics Agent stream ended without a COMPLETE event"
        )
    if not isinstance(rows, list):
        raise AnalyticsUnavailable("Analytics Agent SQL rows were malformed")

    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != REORDER_COLUMNS:
            raise AnalyticsUnavailable(
                "Analytics Agent returned rows outside the governed contract"
            )
        values = [
            row["on_hand_units"],
            row["forecast_units"],
            row["recommended_reorder_quantity"],
        ]
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in values
        ):
            raise AnalyticsUnavailable(
                "Analytics Agent returned non-numeric reorder values"
            )
        on_hand, forecast, recommended = values
        if recommended <= 0 or abs((forecast - on_hand) - recommended) > 1e-9:
            raise AnalyticsUnavailable(
                "Analytics Agent returned an invalid reorder calculation"
            )
        normalized.append(row)
    return normalized


class AnalyticsUnavailable(RuntimeError):
    """Raised when a configured Analytics Agent cannot complete an analysis."""


class ReorderAnalysisProvider(Protocol):
    async def analyze_reorder(
        self, context: DecisionContext
    ) -> ReorderAnalysis: ...


@dataclass(frozen=True)
class AnalyticsAgentConfig:
    base_url: str
    engine_name: str
    timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> "AnalyticsAgentConfig | None":
        enabled = os.getenv("ANALYTICS_AGENT_ENABLED", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not enabled:
            return None
        base_url = os.getenv("ANALYTICS_AGENT_URL")
        engine_name = os.getenv("ANALYTICS_AGENT_ENGINE")
        if not base_url or not engine_name:
            raise AnalyticsUnavailable(
                "ANALYTICS_AGENT_ENABLED requires ANALYTICS_AGENT_URL and "
                "ANALYTICS_AGENT_ENGINE"
            )
        return cls(
            base_url=base_url.rstrip("/"),
            engine_name=engine_name,
            timeout_seconds=float(
                os.getenv("ANALYTICS_AGENT_TIMEOUT_SECONDS", "120")
            ),
        )


class FixtureReorderAnalysisProvider:
    async def analyze_reorder(
        self, _context: DecisionContext
    ) -> ReorderAnalysis:
        rows = [
            {
                "product_id": "SKU-DG-101",
                "on_hand_units": 60,
                "forecast_units": 140,
                "recommended_reorder_quantity": 80,
            },
            {
                "product_id": "SKU-DG-102",
                "on_hand_units": 45,
                "forecast_units": 115,
                "recommended_reorder_quantity": 70,
            },
            {
                "product_id": "SKU-DG-103",
                "on_hand_units": 30,
                "forecast_units": 92,
                "recommended_reorder_quantity": 62,
            },
        ]
        return ReorderAnalysis(
            source="deterministic_fixture",
            question=REORDER_QUESTION,
            answer=(
                "Three Northeast products require reorder because governed "
                "forecast demand exceeds current on-hand inventory."
            ),
            sql=REORDER_SQL,
            columns=list(rows[0]),
            rows=rows,
            chart={
                "mark": "bar",
                "encoding": {
                    "x": {"field": "product_id", "type": "nominal"},
                    "y": {
                        "field": "recommended_reorder_quantity",
                        "type": "quantitative",
                    },
                },
            },
            context_quality={
                "score": 3,
                "label": "Fixture",
                "breakdown": {
                    "reason": "Credential-free deterministic judge demo"
                },
            },
            tool_calls=[],
        )


class AnalyticsAgentClient:
    """Call the Analytics Agent conversation API and retain its full output."""

    def __init__(self, config: AnalyticsAgentConfig):
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        accept: str = "application/json",
    ) -> tuple[str, str]:
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": accept}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.config.base_url}{path}",
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(  # noqa: S310 -- explicitly configured local/service URL
                request, timeout=self.config.timeout_seconds
            ) as response:
                return response.read().decode(), response.headers.get(
                    "Content-Type", ""
                )
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise AnalyticsUnavailable(
                f"Analytics Agent request failed for {path}: {error}"
            ) from error

    async def healthcheck(self) -> bool:
        raw, _ = await asyncio.to_thread(self._request, "GET", "/health")
        try:
            return json.loads(raw).get("status") == "ok"
        except (json.JSONDecodeError, AttributeError):
            return False

    @staticmethod
    def _parse_sse(raw: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for line in raw.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError as error:
                raise AnalyticsUnavailable(
                    "Analytics Agent returned invalid SSE data"
                ) from error
            if isinstance(event, dict):
                events.append(event)
        return events

    async def analyze_reorder(
        self, context: DecisionContext
    ) -> ReorderAnalysis:
        context_note = "\n".join(f"- {fact}" for fact in context.facts)
        question = (
            f"{REORDER_QUESTION}\n\nDataHub context already verified by "
            f"DecisionGraph:\n{context_note}"
        )
        raw_conversation, _ = await asyncio.to_thread(
            self._request,
            "POST",
            "/api/conversations",
            {
                "title": "DecisionGraph Northeast reorder analysis",
                "engine_name": self.config.engine_name,
            },
        )
        try:
            conversation = json.loads(raw_conversation)
            conversation_id = str(conversation["id"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise AnalyticsUnavailable(
                "Analytics Agent did not create a conversation"
            ) from error

        raw_stream, _ = await asyncio.to_thread(
            self._request,
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            {"text": question},
            accept="text/event-stream",
        )
        events = self._parse_sse(raw_stream)
        errors = [
            str(event.get("payload", {}).get("error"))
            for event in events
            if event.get("event") == "ERROR"
            and isinstance(event.get("payload"), dict)
        ]
        if errors:
            raise AnalyticsUnavailable(errors[-1])

        sql_event = next(
            (event for event in reversed(events) if event.get("event") == "SQL"),
            None,
        )
        chart_event = next(
            (
                event
                for event in reversed(events)
                if event.get("event") == "CHART"
            ),
            None,
        )
        sql_payload = (
            sql_event.get("payload", {})
            if isinstance(sql_event, dict)
            else {}
        )
        chart_payload = (
            chart_event.get("payload", {})
            if isinstance(chart_event, dict)
            else {}
        )
        if not isinstance(sql_payload, dict) or not sql_payload.get("sql"):
            raise AnalyticsUnavailable(
                "Analytics Agent completed without a SQL result"
            )
        normalized_rows = _validate_reorder_result(
            sql_payload["sql"], sql_payload.get("rows"), events
        )
        chart = (
            chart_payload.get("vega_lite_spec")
            if isinstance(chart_payload, dict)
            and isinstance(chart_payload.get("vega_lite_spec"), dict)
            else None
        )
        if chart is not None:
            # The SQL event is the authoritative result. Some smaller local
            # models can produce a valid chart design but populate it with
            # illustrative values. Keep the design while binding it to the
            # rows that the configured engine actually returned.
            chart = json.loads(json.dumps(chart))
            chart["data"] = {"values": normalized_rows}
        raw_quality, _ = await asyncio.to_thread(
            self._request,
            "GET",
            f"/api/conversations/{conversation_id}/quality",
        )
        try:
            quality = json.loads(raw_quality)
        except json.JSONDecodeError:
            quality = None
        tool_calls = [
            str(payload["tool_name"])
            for event in events
            if event.get("event") == "TOOL_CALL"
            and isinstance((payload := event.get("payload")), dict)
            and payload.get("tool_name")
        ]
        product_ids = [
            str(row["product_id"])
            for row in normalized_rows
            if row.get("product_id") is not None
        ]
        grounded_answer = (
            "Analytics Agent executed the governed SQL query and returned "
            f"{len(normalized_rows)} Northeast reorder candidates"
            f": {', '.join(product_ids)}."
            if product_ids
            else (
                "Analytics Agent executed the governed SQL query and returned "
                f"{len(normalized_rows)} Northeast reorder candidates."
            )
        )
        return ReorderAnalysis(
            source="datahub_analytics_agent",
            question=REORDER_QUESTION,
            conversation_id=conversation_id,
            engine_name=self.config.engine_name,
            answer=grounded_answer,
            sql=str(sql_payload["sql"]),
            columns=[
                str(column)
                for column in sql_payload.get("columns", [])
            ],
            rows=normalized_rows,
            chart=chart,
            context_quality=quality if isinstance(quality, dict) else None,
            tool_calls=tool_calls,
        )


def analysis_provider_from_environment() -> ReorderAnalysisProvider:
    config = AnalyticsAgentConfig.from_environment()
    if config:
        return AnalyticsAgentClient(config)
    return FixtureReorderAnalysisProvider()
