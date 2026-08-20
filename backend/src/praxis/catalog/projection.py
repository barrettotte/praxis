"""Minimal evidence projections safe to place in agent context."""

from praxis.catalog.memory import CatalogEntry
from praxis.domain import Book, Byte, MuseumObject, Project


def _defined_fields(**fields: object) -> dict[str, object]:
    """Omit absent optional values from agent context."""
    return {name: value for name, value in fields.items() if value is not None and value != ""}


def project_evidence(entry: CatalogEntry) -> dict[str, object]:
    """Return only factual fields required for project recommendation."""
    common: dict[str, object] = {"evidence_id": entry.id, "kind": entry.kind.value}
    match entry.item:
        case Book() as book:
            return (
                common
                | {
                    "title": book.title,
                    "year": book.year,
                    "tags": book.tags,
                }
                | _defined_fields(author=book.author, category=book.category)
            )
        case Project() as project:
            return (
                common
                | {
                    "name": project.name,
                    "description": project.description,
                    "languages": project.languages,
                }
                | _defined_fields(date=project.date)
            )
        case Byte() as byte:
            return common | {
                "name": byte.name,
                "category": byte.category,
                "date": byte.date.isoformat(),
            }
        case MuseumObject() as museum:
            return (
                common
                | {
                    "name": museum.name,
                    "manufacturer": museum.manufacturer,
                    "category": museum.category,
                    "description": museum.description,
                }
                | _defined_fields(year=museum.year)
            )
