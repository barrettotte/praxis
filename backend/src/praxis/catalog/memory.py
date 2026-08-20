"""Read-only in-memory storage for catalog records."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Self

from pydantic import TypeAdapter, ValidationError

from praxis.domain import Book, Byte, MuseumObject, Project

type CatalogItem = Book | Byte | MuseumObject | Project

BOOKS_ADAPTER = TypeAdapter(list[Book])
BYTES_ADAPTER = TypeAdapter(list[Byte])
MUSEUM_ADAPTER = TypeAdapter(list[MuseumObject])
PROJECTS_ADAPTER = TypeAdapter(list[Project])


class CatalogLoadError(ValueError):
    """Raised when a catalog collection cannot be loaded."""


class CatalogKind(StrEnum):
    """The supported catalog record kinds."""

    BOOK = "book"
    PROJECT = "project"
    BYTE = "byte"
    MUSEUM_OBJECT = "museum"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """A catalog item paired with its stable local evidence identifier."""

    id: str
    kind: CatalogKind
    item: CatalogItem


def _entry_identity(item: CatalogItem) -> tuple[CatalogKind, str]:
    match item:
        case Book():
            identity = f"{item.isbn_13 or item.isbn_10}|{item.title}|{item.author}|{item.year}"
            return CatalogKind.BOOK, identity
        case Project():
            return CatalogKind.PROJECT, f"{item.name}|{item.date}"
        case Byte():
            return CatalogKind.BYTE, f"{item.name}|{item.date.isoformat()}"
        case MuseumObject():
            return CatalogKind.MUSEUM_OBJECT, item.id


def catalog_entry(item: CatalogItem) -> CatalogEntry:
    """Pair a validated catalog item with its stable evidence identifier."""
    kind, identity = _entry_identity(item)
    digest = sha256(f"{kind}:{identity}".encode()).hexdigest()[:16]
    return CatalogEntry(id=f"{kind}:{digest}", kind=kind, item=item)


def _load_records[T](path: Path, adapter: TypeAdapter[list[T]]) -> tuple[T, ...]:
    try:
        records = adapter.validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        message = f"Unable to load catalog records from {path}"
        raise CatalogLoadError(message) from error
    return tuple(records)


@dataclass(frozen=True, slots=True)
class InMemoryCatalog:
    """An immutable snapshot of the four catalog collections."""

    books: tuple[Book, ...]
    projects: tuple[Project, ...]
    bytes: tuple[Byte, ...]
    museum_objects: tuple[MuseumObject, ...]

    @classmethod
    def from_directory(cls, directory: Path) -> Self:
        """Load and validate catalog JSON files from a directory."""
        return cls(
            books=_load_records(directory / "books.json", BOOKS_ADAPTER),
            projects=_load_records(directory / "projects.json", PROJECTS_ADAPTER),
            bytes=_load_records(directory / "bytes.json", BYTES_ADAPTER),
            museum_objects=_load_records(directory / "museum.json", MUSEUM_ADAPTER),
        )

    def __iter__(self) -> Iterator[CatalogItem]:
        """Iterate over all records in deterministic collection order."""
        yield from self.books
        yield from self.projects
        yield from self.bytes
        yield from self.museum_objects

    def __len__(self) -> int:
        """Return the total number of records in the snapshot."""
        return sum(
            (
                len(self.books),
                len(self.projects),
                len(self.bytes),
                len(self.museum_objects),
            )
        )

    def entries(self) -> Iterator[CatalogEntry]:
        """Iterate over records with deterministic local evidence identifiers."""
        yield from (catalog_entry(item) for item in self)
