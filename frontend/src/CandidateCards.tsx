import { useId } from "react";

import type { ProjectCandidate, SupportingEvidence } from "./api";

interface CandidateCardsProps {
  candidates: readonly [ProjectCandidate, ProjectCandidate, ProjectCandidate];
  evidence: readonly SupportingEvidence[];
  onSelect: (index: number) => void;
  selectedCandidateIndex: number | null;
  selectionPending: boolean;
}

const SCOPE_LABELS: Record<ProjectCandidate["estimated_scope"], string> = {
  "multi-month": "Multi-month",
  "multi-week": "Multi-week",
  weekend: "Weekend",
};

function evidenceTitle(evidence: SupportingEvidence): string {
  return evidence.kind === "book" ? evidence.title : evidence.name;
}

function evidenceType(evidence: SupportingEvidence): string {
  const labels: Record<SupportingEvidence["kind"], string> = {
    book: "Book",
    byte: "Technical note",
    museum: "Museum object",
    project: "Project",
  };
  return labels[evidence.kind];
}

function evidenceMetadata(evidence: SupportingEvidence): string {
  switch (evidence.kind) {
    case "book":
      return [evidence.author, evidence.year.toString(), evidence.category]
        .filter((value) => value !== null)
        .join(" · ");
    case "project":
      return [evidence.date, ...evidence.languages].filter((value) => value !== null).join(" · ");
    case "byte":
      return `${evidence.category} · ${evidence.date}`;
    case "museum":
      return [evidence.manufacturer, evidence.year?.toString() ?? null, evidence.category]
        .filter((value) => value !== null)
        .join(" · ");
  }
}

export function CandidateCards({
  candidates,
  evidence,
  onSelect,
  selectedCandidateIndex,
  selectionPending,
}: CandidateCardsProps) {
  const headingId = useId();
  const evidenceById = new Map(evidence.map((item) => [item.evidence_id, item]));

  return (
    <section className="candidate-results" aria-busy={selectionPending} aria-labelledby={headingId}>
      <div className="candidate-results-heading">
        <p className="eyebrow">Three directions</p>
        <h3 id={headingId}>Compare project candidates</h3>
      </div>
      <ol className="candidate-grid">
        {candidates.map((candidate, index) => (
          <li key={`${candidate.title}-${index.toString()}`}>
            <article
              className={`candidate-card${selectedCandidateIndex === index ? " candidate-card-selected" : ""}`}
            >
              <div className="candidate-labels">
                <p className="candidate-number">Candidate {(index + 1).toString()}</p>
                <p className="generated-label">AI-generated recommendation</p>
              </div>
              <h4>{candidate.title}</h4>
              <p className="candidate-summary">{candidate.summary}</p>
              <dl className="candidate-facts">
                <div>
                  <dt>Scope</dt>
                  <dd>{SCOPE_LABELS[candidate.estimated_scope]}</dd>
                </div>
                <div>
                  <dt>Technologies</dt>
                  <dd>{candidate.technologies.join(", ")}</dd>
                </div>
              </dl>
              <div className="candidate-detail">
                <h5>Why it fits</h5>
                <p>{candidate.rationale}</p>
              </div>
              <div className="candidate-detail">
                <h5>First milestone</h5>
                <p>{candidate.first_milestone}</p>
              </div>
              <div className="candidate-evidence">
                <h5>Supporting evidence</h5>
                <ul>
                  {candidate.evidence_citations.map((citation) => {
                    const item = evidenceById.get(citation.evidence_id);
                    if (item === undefined) {
                      return null;
                    }
                    return (
                      <li key={item.evidence_id}>
                        <p className="evidence-type">Catalog evidence · {evidenceType(item)}</p>
                        <p className="evidence-title">{evidenceTitle(item)}</p>
                        <p className="evidence-metadata">{evidenceMetadata(item)}</p>
                        <code>{item.evidence_id}</code>
                        <div className="generated-connection">
                          <p className="generated-connection-label">Generated connection</p>
                          <p>{citation.generated_connection}</p>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
              <button
                className="button button-secondary candidate-select-button"
                type="button"
                aria-pressed={selectedCandidateIndex === index}
                disabled={selectionPending}
                onClick={() => {
                  onSelect(index);
                }}
              >
                {selectionPending && selectedCandidateIndex === index
                  ? "Creating brief…"
                  : selectedCandidateIndex === index
                    ? "Selected project"
                    : "Select this project"}
              </button>
            </article>
          </li>
        ))}
      </ol>
    </section>
  );
}
