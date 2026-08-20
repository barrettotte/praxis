"""Catalog storage and query interfaces."""

from praxis.catalog.get import (
    CatalogItemNotFoundError,
    GetCatalogItemRequest,
    get_catalog_item,
)
from praxis.catalog.history import (
    CompareProjectHistoryRequest,
    ProjectHistoryMatch,
    compare_project_history,
)
from praxis.catalog.memory import (
    CatalogEntry,
    CatalogItem,
    CatalogKind,
    CatalogLoadError,
    InMemoryCatalog,
    catalog_entry,
)
from praxis.catalog.projection import project_evidence
from praxis.catalog.search import (
    CatalogSearchResult,
    SearchCatalogRequest,
    catalog_search_text,
    search_catalog,
)

__all__ = [
    "CatalogEntry",
    "CatalogItem",
    "CatalogItemNotFoundError",
    "CatalogKind",
    "CatalogLoadError",
    "CatalogSearchResult",
    "CompareProjectHistoryRequest",
    "GetCatalogItemRequest",
    "InMemoryCatalog",
    "ProjectHistoryMatch",
    "SearchCatalogRequest",
    "catalog_entry",
    "catalog_search_text",
    "compare_project_history",
    "get_catalog_item",
    "project_evidence",
    "search_catalog",
]
