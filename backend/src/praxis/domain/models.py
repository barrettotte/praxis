"""Validated domain models for personal catalog records."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

type NonEmptyString = Annotated[str, Field(min_length=1)]
type YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
type ImageFocus = Annotated[list[float], Field(min_length=2, max_length=2)]


class DomainModel(BaseModel):
    """Apply strict, source-compatible validation to catalog models."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class Book(DomainModel):
    """A book in the personal reference library."""

    title: NonEmptyString
    year: Annotated[int, Field(ge=0)]
    author: str | None = None
    category: NonEmptyString | None = None
    isbn_10: str | None = None
    isbn_13: str | None = None
    language: str | None = None
    lccn: str | None = None
    tags: list[NonEmptyString] = Field(default_factory=list)


class Project(DomainModel):
    """A historical software or hardware project."""

    name: NonEmptyString
    description: NonEmptyString = Field(alias="desc")
    date: YearMonth | None = None
    languages: list[NonEmptyString] = Field(default_factory=list)
    url: NonEmptyString | None = None
    deploy_url: NonEmptyString | None = None
    image: NonEmptyString | None = None
    image_focus: ImageFocus | None = None
    featured: bool = False
    hidden: bool = False


class ModelPart(DomainModel):
    """An independently renderable part of a three-dimensional model."""

    name: NonEmptyString
    src: NonEmptyString
    fallback: NonEmptyString


class ByteModel(DomainModel):
    """Three-dimensional model metadata attached to a byte record."""

    slug: NonEmptyString
    src: NonEmptyString
    fallback: NonEmptyString
    up_axis: NonEmptyString
    description: NonEmptyString
    poster: NonEmptyString | None = None
    parts: list[ModelPart] = Field(default_factory=list[ModelPart])


class Byte(DomainModel):
    """A technical note, build, experiment, or other small artifact."""

    name: NonEmptyString
    date: date
    category: NonEmptyString
    url: NonEmptyString | None = None
    model: ByteModel | None = None


class MuseumObject(DomainModel):
    """An object in the personal computing museum."""

    id: NonEmptyString
    name: NonEmptyString
    manufacturer: NonEmptyString
    year: Annotated[int, Field(ge=0)] | None
    category: NonEmptyString
    image: NonEmptyString
    description: NonEmptyString
    display_year: NonEmptyString | None = None
