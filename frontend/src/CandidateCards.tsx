import { useId } from "react";

import type { ProjectCandidate } from "./api";

interface CandidateCardsProps {
  candidates: readonly [ProjectCandidate, ProjectCandidate, ProjectCandidate];
}

const SCOPE_LABELS: Record<ProjectCandidate["estimated_scope"], string> = {
  "multi-month": "Multi-month",
  "multi-week": "Multi-week",
  weekend: "Weekend",
};

export function CandidateCards({ candidates }: CandidateCardsProps) {
  const headingId = useId();

  return (
    <section className="candidate-results" aria-labelledby={headingId}>
      <div className="candidate-results-heading">
        <p className="eyebrow">Three directions</p>
        <h3 id={headingId}>Compare project candidates</h3>
      </div>
      <ol className="candidate-grid">
        {candidates.map((candidate, index) => (
          <li key={`${candidate.title}-${index.toString()}`}>
            <article className="candidate-card">
              <p className="candidate-number">Candidate {(index + 1).toString()}</p>
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
            </article>
          </li>
        ))}
      </ol>
    </section>
  );
}
