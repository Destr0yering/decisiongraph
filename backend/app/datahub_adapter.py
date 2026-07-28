"""Minimal, explicit DataHub GraphQL adapter for DecisionGraph projections.

This uses only the standard library so deterministic demo mode remains runnable
without a DataHub installation. It is intentionally narrow: native Documents
are a supported way to persist searchable, related decision evidence in
DataHub. Agent-run DataFlow/DataJob projection is the next adapter method.
"""

from dataclasses import dataclass
import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


class DataHubUnavailable(RuntimeError):
    """Raised when an explicitly configured DataHub endpoint cannot be reached."""


@dataclass(frozen=True)
class DataHubConfig:
    server: str
    token: str | None = None
    mcp_mutations_enabled: bool = False
    mcp_package: str = "mcp-server-datahub@0.6.0"

    @classmethod
    def from_environment(cls) -> "DataHubConfig | None":
        server = os.getenv("DATAHUB_GMS_URL")
        if not server:
            return None
        return cls(
            server=server.rstrip("/"),
            token=(
                os.getenv("DATAHUB_GMS_TOKEN")
                or os.getenv("DATAHUB_TOKEN")
            ),
            mcp_mutations_enabled=os.getenv(
                "DATAHUB_MCP_MUTATIONS_ENABLED", ""
            ).lower()
            in {"1", "true", "yes", "on"},
            mcp_package=os.getenv(
                "DATAHUB_MCP_PACKAGE", "mcp-server-datahub@0.6.0"
            ),
        )


class DataHubAdapter:
    def __init__(self, config: DataHubConfig):
        self.config = config

    def _graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        request = Request(f"{self.config.server}/api/graphql", data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 -- configured DataHub endpoint
                payload = json.loads(response.read())
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise DataHubUnavailable(f"Cannot connect to DataHub at {self.config.server}") from error
        if not isinstance(payload, dict):
            raise DataHubUnavailable("DataHub returned an invalid response")
        if payload.get("errors"):
            raise DataHubUnavailable("DataHub rejected the request")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise DataHubUnavailable("DataHub returned no response data")
        return data

    def healthcheck(self) -> bool:
        data = self._graphql("query { me { corpUser { urn } } }", {})
        return bool(data.get("me", {}).get("corpUser", {}).get("urn"))

    def create_decision_document(
        self,
        *,
        decision_id: str,
        title: str,
        summary: str,
        related_assets: list[str],
        existing_urn: str | None = None,
    ) -> str:
        """Create a compact, searchable DataHub projection for a decision."""
        mutation = """
        mutation CreateDecisionDocument($input: CreateDocumentInput!) {
          createDocument(input: $input)
        }
        """
        input_data = {
            "id": f"decisiongraph-{decision_id}",
            "title": title,
            "subType": "DecisionGraphDecision",
            "state": "PUBLISHED",
            "contents": {"text": summary},
            "settings": {"showInGlobalContext": False},
            "relatedAssets": related_assets,
        }
        data = self._graphql(mutation, {"input": input_data})
        urn = data.get("createDocument")
        if not urn:
            raise DataHubUnavailable("DataHub did not return a Document URN")
        return str(urn)

    def get_decision_document(self, urn: str) -> dict[str, object] | None:
        """Read back the compact projection and its related DataHub assets."""
        query = """
        query GetDecisionDocument($urn: String!) {
          document(urn: $urn) {
            urn
            info {
              title
              relatedAssets { asset { urn type } }
            }
            settings { showInGlobalContext }
          }
        }
        """
        data = self._graphql(query, {"urn": urn})
        document = data.get("document")
        return document if isinstance(document, dict) else None


class DataHubMCPAdapter(DataHubAdapter):
    """Persist approved decisions with the official MCP save_document tool."""

    async def create_decision_document(
        self,
        *,
        decision_id: str,
        title: str,
        summary: str,
        related_assets: list[str],
        existing_urn: str | None = None,
    ) -> str:
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport
        except ImportError as error:
            raise DataHubUnavailable(
                "FastMCP is required for MCP document write-back"
            ) from error

        environment = {
            "DATAHUB_GMS_URL": self.config.server,
            "DATAHUB_GMS_TOKEN": self.config.token or "",
            "TOOLS_IS_MUTATION_ENABLED": "true",
            "TOOLS_IS_USER_ENABLED": "false",
            "SAVE_DOCUMENT_TOOL_ENABLED": "true",
        }
        transport = StdioTransport(
            command=sys.executable,
            args=[
                "-m",
                "uv",
                "tool",
                "run",
                self.config.mcp_package,
            ],
            env=environment,
            keep_alive=False,
        )
        parameters: dict[str, object] = {
            "document_type": "Decision",
            "title": title,
            "content": summary,
            "topics": [
                "decisiongraph",
                "governed-decision",
                "approved",
            ],
            "related_assets": related_assets,
        }
        if existing_urn:
            parameters["urn"] = existing_urn

        try:
            async with Client(transport) as client:
                result = await client.call_tool("save_document", parameters)
                data = getattr(result, "data", None)
                if bool(getattr(result, "is_error", False)) or not isinstance(
                    data, dict
                ):
                    raise DataHubUnavailable(
                        "DataHub MCP save_document returned no result"
                    )
                if not data.get("success") or not data.get("urn"):
                    raise DataHubUnavailable(
                        str(data.get("message") or "DataHub document save failed")
                    )
                urn = str(data["urn"])
                readback = await client.call_tool(
                    "get_entities", {"urns": [urn]}
                )
                readback_data = getattr(readback, "data", None)
                if bool(getattr(readback, "is_error", False)) or not isinstance(
                    readback_data, list
                ):
                    raise DataHubUnavailable(
                        "DataHub MCP could not verify the saved Document"
                    )
                if not any(
                    isinstance(item, dict) and item.get("urn") == urn
                    for item in readback_data
                ):
                    raise DataHubUnavailable(
                        "Saved DataHub Document was not returned by read-back"
                    )
                return urn
        except DataHubUnavailable:
            raise
        except Exception as error:
            raise DataHubUnavailable(
                f"DataHub MCP document write-back failed: {error}"
            ) from error


def datahub_adapter_from_config(config: DataHubConfig) -> DataHubAdapter:
    if config.mcp_mutations_enabled:
        return DataHubMCPAdapter(config)
    return DataHubAdapter(config)
