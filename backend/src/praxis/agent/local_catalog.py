"""In-memory implementations of the catalog tools used by candidate generation."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import cast

from strands.types.tools import AgentTool, ToolResult, ToolSpec, ToolUse

from praxis.catalog import (
    CatalogEntry,
    CatalogKind,
    CatalogSearchResult,
    GetCatalogItemRequest,
    InMemoryCatalog,
    SearchCatalogRequest,
    get_catalog_item,
    search_catalog,
)
from praxis.domain.prompt_safety import require_safe_content
from praxis.functions.catalog import execute_catalog_tool
from praxis.tools.contracts import GatewayToolDefinition, gateway_tool_definitions


@dataclass(frozen=True, slots=True)
class LocalCatalogRepository:
    """Adapt authoritative local records to the same handler used by Lambda."""

    catalog: InMemoryCatalog

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        return search_catalog(self.catalog, request)

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        return get_catalog_item(self.catalog, request)

    def project_entries(self) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.catalog.entries() if entry.kind == CatalogKind.PROJECT)


class LocalCatalogTool(AgentTool):
    """Expose a catalog operation with the Gateway's model-facing input schema."""

    def __init__(
        self, definition: GatewayToolDefinition, repository: LocalCatalogRepository
    ) -> None:
        super().__init__()
        self.definition = definition
        self.repository = repository

    @property
    def tool_name(self) -> str:
        return self.definition.name

    @property
    def tool_spec(self) -> ToolSpec:
        return {
            "name": self.tool_name,
            "description": self.definition.description,
            "outputSchema": {
                "json": self.definition.output_schema.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            },
            "inputSchema": {
                "json": self.definition.input_schema.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            },
        }

    @property
    def tool_type(self) -> str:
        return "python"

    def call(self, arguments: object, tool_use_id: str) -> ToolResult:
        """Validate and execute without exposing exception details to the model."""
        try:
            require_safe_content(arguments)
            payload = execute_catalog_tool(self.definition.name, arguments, self.repository)
            require_safe_content(payload)
        except (ValueError, LookupError):
            return {
                "toolUseId": tool_use_id,
                "status": "error",
                "content": [{"text": "Catalog request failed validation or lookup."}],
            }
        return {"toolUseId": tool_use_id, "status": "success", "content": [{"json": payload}]}

    async def stream(
        self, tool_use: ToolUse, invocation_state: dict[str, object], **_: object
    ) -> AsyncGenerator[ToolResult]:
        del invocation_state  # Invocation budgets and evidence collection are enforced by hooks.
        yield self.call(cast("object", tool_use["input"]), tool_use["toolUseId"])


def local_catalog_tools(catalog: InMemoryCatalog) -> tuple[LocalCatalogTool, ...]:
    """Provide the four read-only tools without cloud credentials or network access."""
    repository = LocalCatalogRepository(catalog)
    return tuple(
        LocalCatalogTool(definition, repository) for definition in gateway_tool_definitions()
    )
