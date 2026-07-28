"""Decision context providers, including the official DataHub MCP server."""

from dataclasses import dataclass
import os
import sys
from typing import Protocol

from .models import DecisionContext, Dependency


INVENTORY_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:demo,"
    "fiction_retail.inventory,PROD)"
)
FORECAST_URN = (
    "urn:li:dataset:(urn:li:dataPlatform:demo,"
    "fiction_retail.northeast_forecast,PROD)"
)
DECISION_DEPENDENCIES = [
    Dependency(asset_urn=INVENTORY_URN),
    Dependency(asset_urn=FORECAST_URN),
]


class ContextUnavailable(RuntimeError):
    """Raised when configured decision context cannot be retrieved safely."""


class ContextProvider(Protocol):
    async def fetch_reorder_context(self) -> DecisionContext: ...


@dataclass(frozen=True)
class DataHubMCPConfig:
    gms_url: str
    gms_token: str | None = None
    package: str = "mcp-server-datahub@0.6.0"

    @classmethod
    def from_environment(cls) -> "DataHubMCPConfig | None":
        enabled = os.getenv("DATAHUB_MCP_ENABLED", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not enabled:
            return None
        gms_url = os.getenv("DATAHUB_GMS_URL")
        if not gms_url:
            raise ContextUnavailable(
                "DATAHUB_MCP_ENABLED requires DATAHUB_GMS_URL"
            )
        return cls(
            gms_url=gms_url.rstrip("/"),
            gms_token=(
                os.getenv("DATAHUB_GMS_TOKEN")
                or os.getenv("DATAHUB_TOKEN")
            ),
            package=os.getenv(
                "DATAHUB_MCP_PACKAGE", "mcp-server-datahub@0.6.0"
            ),
        )


class FixtureContextProvider:
    async def fetch_reorder_context(self) -> DecisionContext:
        return DecisionContext(
            source="deterministic_fixture",
            facts=[
                (
                    "Northeast demand forecast exceeds on-hand inventory for "
                    "three products."
                ),
                "Inventory freshness was valid when the decision was generated.",
            ],
            snapshot={"mode": "offline-demo"},
        )


def _tool_data(result: object, tool_name: str) -> object:
    if bool(getattr(result, "is_error", False)):
        raise ContextUnavailable(f"DataHub MCP tool {tool_name} failed")
    data = getattr(result, "data", None)
    if data is None:
        raise ContextUnavailable(
            f"DataHub MCP tool {tool_name} returned no structured data"
        )
    return data


def _entity_errors(entities: object) -> list[str]:
    if not isinstance(entities, list):
        return ["get_entities returned an unexpected payload"]
    return [
        str(item["error"])
        for item in entities
        if isinstance(item, dict) and item.get("error")
    ]


def _schema_count(schema: object) -> int:
    if isinstance(schema, list):
        return len(schema)
    if isinstance(schema, dict):
        for key in ("fields", "schemaFields", "results"):
            value = schema.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def _entity_by_urn(entities: object, urn: str) -> dict[str, object]:
    if not isinstance(entities, list):
        raise ContextUnavailable("get_entities returned an unexpected payload")
    for item in entities:
        if isinstance(item, dict) and item.get("urn") == urn:
            return item
    raise ContextUnavailable(f"DataHub MCP did not return {urn}")


def _custom_properties(entity: dict[str, object]) -> dict[str, str]:
    properties = entity.get("properties")
    if not isinstance(properties, dict):
        return {}
    values = properties.get("customProperties")
    if not isinstance(values, list):
        return {}
    return {
        str(item["key"]): str(item["value"])
        for item in values
        if isinstance(item, dict)
        and item.get("key") is not None
        and item.get("value") is not None
    }


def _context_entity_snapshot(entity: dict[str, object]) -> dict[str, object]:
    editable = entity.get("editableProperties")
    description = (
        editable.get("description")
        if isinstance(editable, dict)
        else None
    )
    return {
        "urn": entity.get("urn"),
        "name": entity.get("name"),
        "description": description,
        "custom_properties": _custom_properties(entity),
        "ownership": entity.get("ownership", {}),
        "tags": entity.get("tags", []),
        "glossary_terms": entity.get("glossaryTerms", []),
        "domain": entity.get("domain"),
        "structured_properties": entity.get("structuredProperties", []),
        "health": entity.get("health", []),
    }


def _context_schema_snapshot(schema: object) -> object:
    if not isinstance(schema, dict):
        return schema
    return {
        key: schema.get(key)
        for key in ("urn", "fields", "totalFields", "returned")
        if key in schema
    }


def _lineage_count(lineage: object) -> int:
    if isinstance(lineage, list):
        return len(lineage)
    if isinstance(lineage, dict):
        for key in (
            "searchResults",
            "entities",
            "relationships",
            "results",
            "nodes",
        ):
            value = lineage.get(key)
            if isinstance(value, list):
                return len(value)
        return sum(
            _lineage_count(lineage.get(direction))
            for direction in ("upstreams", "downstreams")
            if direction in lineage
        )
    return 0


class DataHubMCPContextProvider:
    """Fetch auditable decision inputs through DataHub's official MCP server."""

    def __init__(self, config: DataHubMCPConfig):
        self.config = config

    async def fetch_reorder_context(self) -> DecisionContext:
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport
        except ImportError as error:
            raise ContextUnavailable(
                "FastMCP is not installed; install DecisionGraph dependencies"
            ) from error

        environment = {
            "DATAHUB_GMS_URL": self.config.gms_url,
            "DATAHUB_GMS_TOKEN": self.config.gms_token or "",
            "TOOLS_IS_MUTATION_ENABLED": "false",
            "TOOLS_IS_USER_ENABLED": "false",
        }
        transport = StdioTransport(
            command=sys.executable,
            args=[
                "-m",
                "uv",
                "tool",
                "run",
                self.config.package,
            ],
            env=environment,
            keep_alive=False,
        )

        try:
            async with Client(transport) as client:
                entity_result = await client.call_tool(
                    "get_entities",
                    {
                        "urns": [
                            INVENTORY_URN,
                            FORECAST_URN,
                        ]
                    },
                )
                inventory_schema_result = await client.call_tool(
                    "list_schema_fields",
                    {"urn": INVENTORY_URN, "limit": 100},
                )
                forecast_schema_result = await client.call_tool(
                    "list_schema_fields",
                    {"urn": FORECAST_URN, "limit": 100},
                )
                inventory_lineage_result = await client.call_tool(
                    "get_lineage",
                    {
                        "urn": INVENTORY_URN,
                        "upstream": False,
                        "max_hops": 2,
                        "max_results": 100,
                    },
                )
                forecast_lineage_result = await client.call_tool(
                    "get_lineage",
                    {
                        "urn": FORECAST_URN,
                        "upstream": False,
                        "max_hops": 2,
                        "max_results": 100,
                    },
                )
        except Exception as error:
            raise ContextUnavailable(
                f"Cannot retrieve context through DataHub MCP: {error}"
            ) from error

        entities = _tool_data(entity_result, "get_entities")
        errors = _entity_errors(entities)
        if errors:
            raise ContextUnavailable("; ".join(errors))

        inventory_schema = _tool_data(
            inventory_schema_result, "list_schema_fields"
        )
        forecast_schema = _tool_data(
            forecast_schema_result, "list_schema_fields"
        )
        inventory_lineage = _tool_data(
            inventory_lineage_result, "get_lineage"
        )
        forecast_lineage = _tool_data(
            forecast_lineage_result, "get_lineage"
        )
        inventory_fields = _schema_count(inventory_schema)
        forecast_fields = _schema_count(forecast_schema)
        if not inventory_fields or not forecast_fields:
            raise ContextUnavailable(
                "DataHub MCP returned incomplete schema context"
            )
        inventory_entity = _entity_by_urn(entities, INVENTORY_URN)
        forecast_entity = _entity_by_urn(entities, FORECAST_URN)
        inventory_properties = _custom_properties(inventory_entity)
        forecast_properties = _custom_properties(forecast_entity)
        reorder_candidates = inventory_properties.get("reorder_candidates")
        freshness = inventory_properties.get("freshness_status")
        horizon = forecast_properties.get("forecast_horizon_days")
        if not reorder_candidates or not freshness or not horizon:
            raise ContextUnavailable(
                "DataHub MCP context is missing required decision properties"
            )

        return DecisionContext(
            source="datahub_mcp_server",
            tools=[
                "get_entities",
                "list_schema_fields",
                "get_lineage",
            ],
            facts=[
                (
                    "DataHub MCP metadata identifies "
                    f"{reorder_candidates} governed Northeast reorder candidates."
                ),
                (
                    f"Inventory freshness is {freshness}; the approved demand "
                    f"forecast covers {horizon} days."
                ),
                (
                    "DataHub MCP returned "
                    f"{inventory_fields} inventory fields and "
                    f"{forecast_fields} forecast fields."
                ),
                (
                    "DataHub MCP traced "
                    f"{_lineage_count(inventory_lineage)} inventory and "
                    f"{_lineage_count(forecast_lineage)} forecast downstream "
                    "lineage relationships."
                ),
            ],
            snapshot={
                "entities": [
                    _context_entity_snapshot(inventory_entity),
                    _context_entity_snapshot(forecast_entity),
                ],
                "schemas": {
                    INVENTORY_URN: _context_schema_snapshot(inventory_schema),
                    FORECAST_URN: _context_schema_snapshot(forecast_schema),
                },
                "lineage": {
                    INVENTORY_URN: inventory_lineage,
                    FORECAST_URN: forecast_lineage,
                },
            },
        )


def context_provider_from_environment() -> ContextProvider:
    config = DataHubMCPConfig.from_environment()
    if config:
        return DataHubMCPContextProvider(config)
    return FixtureContextProvider()
