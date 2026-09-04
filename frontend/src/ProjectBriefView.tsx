import { useId } from "react";

import type { SelectCandidateResult } from "./api";

interface ProjectBriefViewProps {
  result: SelectCandidateResult;
}

export function ProjectBriefView({ result }: ProjectBriefViewProps) {
  const headingId = useId();
  const { brief, candidate } = result;

  return (
    <section className="project-brief" aria-labelledby={headingId}>
      <p className="eyebrow">Generated project brief</p>
      <h3 id={headingId}>{candidate.title}</h3>
      <p className="generated-notice">
        This implementation plan is AI-generated from the selected recommendation and its cited
        catalog evidence.
      </p>
      <div className="brief-overview">
        <div>
          <h4>Objective</h4>
          <p>{brief.objective}</p>
        </div>
        <div>
          <h4>Scope</h4>
          <p>{brief.scope}</p>
        </div>
      </div>
      <div className="brief-section">
        <h4>Technical approach</h4>
        <ol className="brief-approach">
          {brief.technical_approach.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
      <div className="brief-section brief-boundaries">
        <div>
          <h4>Assumptions</h4>
          <ul>
            {brief.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Out of scope</h4>
          <ul>
            {brief.out_of_scope.map((exclusion) => (
              <li key={exclusion}>{exclusion}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className="brief-section">
        <h4>Deliverables</h4>
        <ul className="brief-deliverables">
          {brief.deliverables.map((deliverable) => (
            <li key={deliverable}>{deliverable}</li>
          ))}
        </ul>
      </div>
      <div className="brief-section">
        <h4>Milestones</h4>
        <ol className="brief-milestones">
          {brief.milestones.map((milestone) => (
            <li key={milestone.title}>
              <h5>{milestone.title}</h5>
              <p>
                <strong>Deliverable:</strong> {milestone.deliverable}
              </p>
              <p>
                <strong>Verify:</strong> {milestone.verification}
              </p>
            </li>
          ))}
        </ol>
      </div>
      <div className="brief-section">
        <h4>Risks and mitigations</h4>
        <dl className="brief-risks">
          {brief.risks.map((risk) => (
            <div key={risk.risk}>
              <dt>{risk.risk}</dt>
              <dd>{risk.mitigation}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="brief-section">
        <h4>Acceptance criteria</h4>
        <ol className="brief-criteria">
          {brief.acceptance_criteria.map((criterion) => (
            <li key={criterion.criterion}>
              <p>{criterion.criterion}</p>
              <p>
                <strong>Verify:</strong> {criterion.verification}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
