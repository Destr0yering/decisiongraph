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


REORDER_QUESTION = (
    "Using only the governed Fiction Retail inventory and Northeast forecast "
    "datasets, identify products whose forecast demand exceeds on-hand "
    "inventory. Return the product_id, on_hand_units, forecast_units, and "
    "recommended_reorder_quantity. Include the SQL and a chart."
)


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
            sql=(
                "SELECT i.product_id, i.on_hand_units, f.forecast_units, "
                "f.forecast_units - i.on_hand_units AS "
                "recommended_reorder_quantity FROM fiction_retail.inventory i "
                "JOIN fiction_retail.northeast_forecast f "
                "ON f.product_id = i.product_id AND f.region = i.region "
                "WHERE i.region = 'Northeast' "
                "AND f.forecast_units > i.on_hand_units"
            ),
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
        complete_event = next(
            (
                event
                for event in reversed(events)
                if event.get("event") == "COMPLETE"
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
        complete_payload = (
            complete_event.get("payload", {})
            if isinstance(complete_event, dict)
            else {}
        )
        if not isinstance(sql_payload, dict) or not sql_payload.get("sql"):
            raise AnalyticsUnavailable(
                "Analytics Agent completed without a SQL result"
            )
        rows = sql_payload.get("rows", [])
        if not isinstance(rows, list):
            rows = []
        normalized_rows = [
            row for row in rows if isinstance(row, dict)
        ]
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
        return ReorderAnalysis(
            source="datahub_analytics_agent",
            question=REORDER_QUESTION,
            conversation_id=conversation_id,
            engine_name=self.config.engine_name,
            answer=str(
                complete_payload.get("text")
                or "Analytics Agent returned a governed reorder analysis."
            ),
            sql=str(sql_payload["sql"]),
            columns=[
                str(column)
                for column in sql_payload.get("columns", [])
            ],
            rows=normalized_rows,
            chart=(
                chart_payload.get("vega_lite_spec")
                if isinstance(chart_payload, dict)
                and isinstance(
                    chart_payload.get("vega_lite_spec"), dict
                )
                else None
            ),
            context_quality=quality if isinstance(quality, dict) else None,
            tool_calls=tool_calls,
        )


def analysis_provider_from_environment() -> ReorderAnalysisProvider:
    config = AnalyticsAgentConfig.from_environment()
    if config:
        return AnalyticsAgentClient(config)
    return FixtureReorderAnalysisProvider()
