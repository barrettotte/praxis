"""Domain types for the Praxis catalog."""

from praxis.domain.candidate_validation import (
    CandidateOutputValidationError,
    candidate_output_schema,
    validate_candidate_output,
)
from praxis.domain.candidates import EvidenceReference, ProjectCandidate, ProjectCandidateSet
from praxis.domain.models import (
    Book,
    Byte,
    ByteModel,
    ModelPart,
    MuseumObject,
    Project,
)

__all__ = [
    "Book",
    "Byte",
    "ByteModel",
    "CandidateOutputValidationError",
    "EvidenceReference",
    "ModelPart",
    "MuseumObject",
    "Project",
    "ProjectCandidate",
    "ProjectCandidateSet",
    "candidate_output_schema",
    "validate_candidate_output",
]
