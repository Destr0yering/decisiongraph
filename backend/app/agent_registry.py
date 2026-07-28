"""Register DecisionGraph, its skill, and its tools in DataHub."""

from __future__ import annotations

from dataclasses import dataclass

from .datahub_adapter import DataHubConfig
from .models import AgentRegistration


class AgentRegistryUnavailable(RuntimeError):
    """Raised when Agent Registry registration cannot be completed."""


def agent_registry_sdk_status() -> tuple[bool, str]:
    """Report whether the installed DataHub SDK includes Agent Registry entities."""
    try:
        from datahub.api.entities.agent.agent import Agent  # noqa: F401
        from datahub.api.entities.agent.agent_skill import AgentSkill  # noqa: F401
        from datahub.api.entities.agent.api import Api  # noqa: F401
    except ImportError:
        return (
            False,
            "The installed DataHub SDK does not include Agent Registry entity "
            "APIs. Use a DataHub SDK release that provides "
            "datahub.api.entities.agent.",
        )
    return True, "Agent Registry SDK entities are available."


@dataclass(frozen=True)
class DecisionGraphAgentRegistrar:
    config: DataHubConfig

    def register(self, consumed_dataset_urns: list[str]) -> AgentRegistration:
        try:
            from datahub.api.entities.agent.agent import Agent
            from datahub.api.entities.agent.agent_skill import (
                AgentSkill,
                SkillSourceRepository,
            )
            from datahub.api.entities.agent.api import Api, ApiParam
            from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
        except ImportError as error:
            _, detail = agent_registry_sdk_status()
            raise AgentRegistryUnavailable(
                detail
            ) from error

        graph = DataHubGraph(
            DatahubClientConfig(
                server=self.config.server,
                token=self.config.token,
            )
        )
        try:
            tools = [
                Api(
                    id="decisiongraph.propose-decision",
                    name="propose_decision",
                    subtypes=["REST_ENDPOINT"],
                    description=(
                        "Retrieve governed context and create a pending "
                        "evidence-bound operational decision."
                    ),
                    method="POST",
                    path="/api/v1/decisions/run",
                    returns=[ApiParam(name="decision", data_type="object")],
                ),
                Api(
                    id="decisiongraph.approve-decision",
                    name="approve_decision",
                    subtypes=["REST_ENDPOINT"],
                    description=(
                        "Approve a pending decision and persist its DataHub "
                        "Document projection."
                    ),
                    method="POST",
                    path="/api/v1/decisions/{decision_id}/approve",
                    parameters=[
                        ApiParam(
                            name="decision_id",
                            data_type="string",
                            required=True,
                        )
                    ],
                    returns=[ApiParam(name="decision", data_type="object")],
                ),
                Api(
                    id="decisiongraph.invalidate-decision",
                    name="invalidate_decision",
                    subtypes=["REST_ENDPOINT"],
                    description=(
                        "Recall approved decisions whose governed evidence "
                        "has changed."
                    ),
                    method="POST",
                    path="/api/v1/events/invalidation",
                    returns=[
                        ApiParam(name="decisions", data_type="array<object>")
                    ],
                ),
                Api(
                    id="decisiongraph.revalidate-decision",
                    name="revalidate_decision",
                    subtypes=["REST_ENDPOINT"],
                    description=(
                        "Retrieve fresh context and create a replacement "
                        "decision linked to its prior revision."
                    ),
                    method="POST",
                    path="/api/v1/decisions/{decision_id}/revalidate",
                    parameters=[
                        ApiParam(
                            name="decision_id",
                            data_type="string",
                            required=True,
                        )
                    ],
                    returns=[ApiParam(name="decision", data_type="object")],
                ),
                Api(
                    id="decisiongraph.compare-revisions",
                    name="compare_revisions",
                    subtypes=["REST_ENDPOINT"],
                    description=(
                        "Compare prior and current evidence and identify "
                        "affected workflow routines."
                    ),
                    method="GET",
                    path="/api/v1/decisions/{decision_id}/comparison",
                    parameters=[
                        ApiParam(
                            name="decision_id",
                            data_type="string",
                            required=True,
                        )
                    ],
                    returns=[ApiParam(name="comparison", data_type="object")],
                ),
            ]
            tool_urns = [str(tool.emit(graph)) for tool in tools]
            skill = AgentSkill(
                id="evidence-bound-decision-governance",
                name="Evidence-Bound Decision Governance",
                description=(
                    "Ground operational decisions in DataHub context, require "
                    "approval, persist the result, and recall it when evidence "
                    "changes."
                ),
                instructions=(
                    "Resolve governed assets, capture schema and lineage, "
                    "compute the recommendation, show the evidence and impact "
                    "plan, require approval, save a Decision Document, verify "
                    "the write, and revalidate when evidence changes."
                ),
                source_repository=SkillSourceRepository(
                    url="https://github.com/Destr0yering/decisiongraph",
                    path="skills/datahub-decision-governance/SKILL.md",
                ),
                required_tools=tool_urns,
            )
            skill_urn = str(skill.emit(graph))
            agent = Agent(
                id="decisiongraph",
                name="DecisionGraph",
                description=(
                    "A DataHub-native decision memory and recall agent for "
                    "evidence-bound operational actions."
                ),
                skills=[skill_urn],
                tools=tool_urns,
                consumes_datasets=consumed_dataset_urns,
                platform="custom",
                source_type="EXTERNAL",
            )
            agent_urn = str(agent.emit(graph))
        except Exception as error:
            raise AgentRegistryUnavailable(
                f"DataHub Agent Registry rejected registration: {error}"
            ) from error
        finally:
            graph.close()

        return AgentRegistration(
            agent_urn=agent_urn,
            skill_urn=skill_urn,
            tool_urns=tool_urns,
            consumed_dataset_urns=consumed_dataset_urns,
        )
