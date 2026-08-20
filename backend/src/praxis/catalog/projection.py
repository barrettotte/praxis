"""Minimal evidence projections safe to place in agent context."""

from praxis.catalog.memory import CatalogEntry
from praxis.domain import Book, Byte, MuseumObject, Project


def project_evidence(entry: CatalogEntry) -> dict[str, object]:
    """Return only factual fields required for project recommendation."""
    common: dict[str, object] = {"evidence_id": entry.id, "kind": entry.kind.value}
    match entry.item:
        case Book() as book:
            return common | {
                "title": book.title,
                "author": book.author,
                "year": book.year,
                "category": book.category,
                "tags": book.tags,
            }
        case Project() as project:
            return common | {
                "name": project.name,
                "description": project.description,
                "date": project.date,
                "languages": project.languages,
            }
        case Byte() as byte:
            return common | {
                "name": byte.name,
                "category": byte.category,
                "date": byte.date.isoformat(),
            }
        case MuseumObject() as museum:
            return common | {
                "name": museum.name,
                "manufacturer": museum.manufacturer,
                "year": museum.year,
                "category": museum.category,
                "description": museum.description,
            }
