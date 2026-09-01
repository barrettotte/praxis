import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateCards } from "./CandidateCards";
import type { ProjectCandidate, SupportingEvidence } from "./api";

const candidates: [ProjectCandidate, ProjectCandidate, ProjectCandidate] = [
  {
    estimated_scope: "weekend",
    evidence_citations: [
      {
        evidence_id: "book:0000000000000001",
        generated_connection: "Connects motor theory to a compact experiment.",
      },
    ],
    first_milestone: "Measure the field around a simple coil.",
    rationale: "Starts with an observable magnetic field.",
    summary: "Build and measure a small electromagnet.",
    technologies: ["Python", "Microcontroller"],
    title: "Electromagnet field mapper",
  },
  {
    estimated_scope: "multi-week",
    evidence_citations: [
      {
        evidence_id: "project:0000000000000002",
        generated_connection: "Connects AC theory to motor control.",
      },
    ],
    first_milestone: "Simulate one energized stator phase.",
    rationale: "Makes rotating magnetic fields visible.",
    summary: "Visualize a motor stator field over time.",
    technologies: ["TypeScript"],
    title: "Rotating-field visualizer",
  },
  {
    estimated_scope: "multi-month",
    evidence_citations: [
      {
        evidence_id: "byte:0000000000000003",
        generated_connection: "Connects motor construction to measured behavior.",
      },
    ],
    first_milestone: "Characterize one motor under no load.",
    rationale: "Combines measurement, control, and motor theory.",
    summary: "Create a bench for comparing small motors.",
    technologies: ["Python", "Electronics"],
    title: "Motor characterization bench",
  },
];

const evidence: SupportingEvidence[] = [
  {
    author: "James Clerk Maxwell",
    category: "Physics",
    evidence_id: "book:0000000000000001",
    kind: "book",
    tags: ["Electromagnetism"],
    title: "A Treatise on Electricity and Magnetism",
    year: 1873,
  },
  {
    date: "2026-08",
    description: "Interactive motor-field visualization.",
    evidence_id: "project:0000000000000002",
    kind: "project",
    languages: ["TypeScript"],
    name: "Motor field explorer",
  },
  {
    category: "Electronics",
    date: "2026-08-30",
    evidence_id: "byte:0000000000000003",
    kind: "byte",
    name: "Measuring motor current",
  },
];

const scopeLabels: Record<ProjectCandidate["estimated_scope"], string> = {
  "multi-month": "Multi-month",
  "multi-week": "Multi-week",
  weekend: "Weekend",
};

describe("CandidateCards", () => {
  it("renders the same comparison fields for all three candidates", () => {
    render(<CandidateCards candidates={candidates} evidence={evidence} />);

    expect(screen.getByRole("heading", { name: "Compare project candidates" })).toBeVisible();
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(3);

    for (const [index, candidate] of candidates.entries()) {
      const cardElement = cards[index];
      if (cardElement === undefined) {
        throw new Error("Expected one card per candidate");
      }
      const card = within(cardElement);
      expect(card.getByRole("heading", { name: candidate.title })).toBeVisible();
      expect(card.getByText(candidate.summary)).toBeVisible();
      expect(card.getByText(candidate.rationale)).toBeVisible();
      expect(card.getByText(candidate.first_milestone)).toBeVisible();
      expect(card.getByText(scopeLabels[candidate.estimated_scope])).toBeVisible();
      expect(card.getByText(candidate.technologies.join(", "))).toBeVisible();
      const supportingRecord = evidence[index];
      if (supportingRecord === undefined) {
        throw new Error("Expected one supporting record per candidate");
      }
      const title =
        supportingRecord.kind === "book" ? supportingRecord.title : supportingRecord.name;
      expect(card.getByText(title)).toBeVisible();
      expect(card.getByText(supportingRecord.evidence_id)).toBeVisible();
    }
  });
});
