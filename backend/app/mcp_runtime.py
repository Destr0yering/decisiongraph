"""Shared runtime configuration for official DataHub MCP subprocesses."""

import os


def datahub_mcp_environment(
    *,
    gms_url: str,
    gms_token: str | None,
    mutations_enabled: bool,
    save_document_enabled: bool = False,
) -> dict[str, str]:
    """Build a predictable environment for a DataHub MCP subprocess.

    Telemetry is disabled by default because an unreachable telemetry endpoint
    can block the MCP initialization handshake. Operators can explicitly opt
    back in through DATAHUB_TELEMETRY_ENABLED.
    """

    environment = {
        "DATAHUB_GMS_URL": gms_url,
        "DATAHUB_GMS_TOKEN": gms_token or "",
        "DATAHUB_TELEMETRY_ENABLED": os.getenv(
            "DATAHUB_TELEMETRY_ENABLED", "false"
        ),
        "TOOLS_IS_MUTATION_ENABLED": (
            "true" if mutations_enabled else "false"
        ),
        "TOOLS_IS_USER_ENABLED": "false",
    }
    if save_document_enabled:
        environment["SAVE_DOCUMENT_TOOL_ENABLED"] = "true"
    return environment
