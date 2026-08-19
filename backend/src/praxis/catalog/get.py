"""Local catalog item lookup."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from praxis.catalog.memory import CatalogEntry, InMemoryCatalog

CATALOG_ID_PATTERN = r"^(book|byte|museum|project):[0-9a-f]{16}$"


class GetCatalogItemRequest(BaseModel):
    """Validated input for catalog item lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: Annotated[str, Field(pattern=CATALOG_ID_PATTERN)]


class CatalogItemNotFoundError(LookupError):
    """Raised when an evidence identifier is absent from the catalog."""


def get_catalog_item(catalog: InMemoryCatalog, request: GetCatalogItemRequest) -> CatalogEntry:
    """Return the catalog entry identified by a local evidence ID."""
    entry = next((entry for entry in catalog.entries() if entry.id == request.id), None)
    if entry is None:
        message = f"Catalog item not found: {request.id}"
        raise CatalogItemNotFoundError(message)
    return entry
