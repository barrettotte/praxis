import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GoalEntry } from "./GoalEntry";
import { SensitiveInputError } from "./api";
import type {
  ApiClient,
  CreateSessionResult,
  ProjectCandidate,
  SelectCandidateResult,
} from "./api";

const candidate: ProjectCandidate = {
  candidateId: "candidate_1",
  estimated_scope: "weekend",
  evidence_citations: [
    {
      evidence_id: "book:0f5ba253568e4836",
      generated_connection: "The evidence supports this learning path.",
    },
  ],
  first_milestone: "Build the smallest working instruction selector.",
  rationale: "It provides a focused way to practice compiler implementation.",
  summary: "Build a compact compiler backend exercise.",
  technologies: ["Python"],
  title: "Compiler backend exercise",
};

const result: CreateSessionResult = {
  candidates: [
    candidate,
    { ...candidate, candidateId: "candidate_2", title: "Compiler backend visualizer" },
    { ...candidate, candidateId: "candidate_3", title: "Compiler backend test bench" },
  ],
  evidence: [
    {
      author: "Quentin Colombet",
      category: "Compilers",
      evidence_id: "book:0f5ba253568e4836",
      kind: "book",
      tags: [],
      title: "Compiler Backend Development",
      year: 2025,
    },
  ],
  sessionId: "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
};

function selectionResult(candidate: ProjectCandidate): SelectCandidateResult {
  return {
    brief: {
      acceptance_criteria: [1, 2, 3].map((number) => ({
        criterion: `Criterion ${number.toString()} has a measurable result.`,
        verification: `Verification method ${number.toString()}.`,
      })),
      assumptions: ["Python is available.", "A local test runner is available."],
      deliverables: ["A documented input model.", "A tested instruction selector."],
      milestones: [
        {
          deliverable: "Observable deliverable 1",
          title: "Milestone 1",
          verification: "Verification method 1",
        },
        {
          deliverable: "Observable deliverable 2",
          title: "Milestone 2",
          verification: "Verification method 2",
        },
        {
          deliverable: "Observable deliverable 3",
          title: "Milestone 3",
          verification: "Verification method 3",
        },
      ],
      objective: "Build a compact compiler backend.",
      out_of_scope: ["Register allocation.", "Multiple target architectures."],
      risks: [
        { mitigation: "Bound the target.", risk: "The target is too broad." },
        { mitigation: "Keep snapshots.", risk: "Generated code is difficult to debug." },
      ],
      scope: "Implement one expression-lowering path over a weekend.",
      technical_approach: [
        "Define a JSON expression model and validate sample inputs.",
        "Lower each expression into a target-instruction list.",
        "Execute the instruction list and compare its numeric result.",
      ],
    },
    candidate,
    candidateId: candidate.candidateId,
    evidence: result.evidence,
    sessionId: result.sessionId,
  };
}

function createApiClient(
  createSession = vi.fn().mockResolvedValue(result),
  selectCandidate = vi
    .fn()
    .mockImplementation((_sessionId: string, candidateId: ProjectCandidate["candidateId"]) => {
      const selected = result.candidates.find((item) => item.candidateId === candidateId);
      if (selected === undefined) {
        throw new Error("Unknown candidate fixture");
      }
      return Promise.resolve(selectionResult(selected));
    }),
): ApiClient {
  return { createSession, selectCandidate };
}

describe("GoalEntry", () => {
  it("submits a normalized goal within the public API limit", async () => {
    const createSession = vi.fn().mockResolvedValue(result);
    render(<GoalEntry api={createApiClient(createSession)} />);

    const goal = screen.getByLabelText("Goal or interest");
    expect(goal).toHaveAttribute("maxlength", "4000");
    fireEvent.change(goal, {
      target: { value: "  Build a compiler backend over two weekends.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    expect(goal).toHaveValue("Build a compiler backend over two weekends.");
    expect(createSession).toHaveBeenCalledWith("Build a compiler backend over two weekends.");
    expect(await screen.findByText("Three candidates are ready.")).toHaveAttribute(
      "role",
      "status",
    );
    expect(screen.getByRole("heading", { name: "Compare project candidates" })).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getAllByText("Compiler Backend Development")).toHaveLength(3);
  });

  it("rejects a goal containing only whitespace", () => {
    const createSession = vi.fn();
    render(<GoalEntry api={createApiClient(createSession)} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    const error = screen.getByRole("alert");
    expect(error).toHaveTextContent("Describe what you want to learn or build.");
    expect(screen.getByLabelText("Goal or interest")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Goal or interest")).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining(error.id),
    );
    expect(createSession).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows truthful progress while the buffered request is pending", async () => {
    let resolveRequest: ((value: CreateSessionResult) => void) | undefined;
    const pendingRequest = new Promise<CreateSessionResult>((resolve) => {
      resolveRequest = resolve;
    });
    render(<GoalEntry api={createApiClient(vi.fn().mockReturnValue(pendingRequest))} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Praxis is searching your evidence and preparing three candidates…",
    );
    expect(screen.getByLabelText("Goal or interest")).toBeDisabled();
    expect(screen.getByLabelText("Goal or interest").closest("form")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.getByRole("button", { name: "Finding projects…" })).toBeDisabled();

    resolveRequest?.(result);
    expect(await screen.findByText("Three candidates are ready.")).toHaveAttribute(
      "role",
      "status",
    );
  });

  it("asks users to remove credentials before resubmitting", async () => {
    render(
      <GoalEntry api={createApiClient(vi.fn().mockRejectedValue(new SensitiveInputError()))} />,
    );
    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "api_key=synthetic-credential" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Remove passwords, API keys, or tokens from your goal.",
    );
    expect(screen.getByLabelText("Goal or interest")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Find project ideas" })).toBeEnabled();
  });

  it("shows a retryable error without exposing dependency details", async () => {
    const api = createApiClient(
      vi.fn().mockRejectedValue(new Error("internal provider diagnostic")),
    );
    render(<GoalEntry api={api} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Recommendations could not be created. Try again.",
    );
    expect(screen.queryByText("internal provider diagnostic")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find project ideas" })).toBeEnabled();
  });

  it("clears completed candidates when the goal changes", async () => {
    render(<GoalEntry api={createApiClient()} />);

    const goal = screen.getByLabelText("Goal or interest");
    fireEvent.change(goal, { target: { value: "Learn compiler backends" } });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));
    expect(
      await screen.findByRole("heading", { name: "Compare project candidates" }),
    ).toBeVisible();

    fireEvent.change(goal, { target: { value: "Learn electric motors" } });

    expect(
      screen.queryByRole("heading", { name: "Compare project candidates" }),
    ).not.toBeInTheDocument();
  });

  it("keeps exactly one candidate selected and allows replacing it", async () => {
    render(<GoalEntry api={createApiClient()} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));
    await screen.findByRole("heading", { name: "Compare project candidates" });

    const cards = screen.getAllByRole("article");
    const firstCard = cards[0];
    const secondCard = cards[1];
    if (firstCard === undefined || secondCard === undefined) {
      throw new Error("Expected candidate cards");
    }
    fireEvent.click(within(firstCard).getByRole("button", { name: "Select this project" }));
    expect(
      await within(firstCard).findByRole("button", { name: "Selected project" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(within(secondCard).getByRole("button", { name: "Select this project" }));
    expect(
      await within(secondCard).findByRole("button", { name: "Selected project" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(within(firstCard).getByRole("button", { name: "Select this project" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("requests and renders the generated brief for the selected candidate", async () => {
    const selectCandidate = vi.fn().mockResolvedValue(selectionResult(result.candidates[1]));
    render(<GoalEntry api={createApiClient(vi.fn().mockResolvedValue(result), selectCandidate)} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));
    const cards = await screen.findAllByRole("article");
    const secondCard = cards[1];
    if (secondCard === undefined) {
      throw new Error("Expected second candidate card");
    }
    fireEvent.click(within(secondCard).getByRole("button", { name: "Select this project" }));

    expect(
      await screen.findByRole("heading", { name: "Compiler backend visualizer" }),
    ).toBeVisible();
    expect(screen.getByText("Build a compact compiler backend.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Technical approach" })).toBeVisible();
    expect(
      screen.getByText("Define a JSON expression model and validate sample inputs."),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Milestones" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Assumptions" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Out of scope" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Deliverables" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Risks and mitigations" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Acceptance criteria" })).toBeVisible();
    expect(screen.getByText("Observable deliverable 1")).toBeVisible();
    expect(screen.getByText("Verification method 1")).toBeVisible();
    expect(screen.getByText("Project brief is ready.")).toHaveAttribute("role", "status");
    expect(selectCandidate).toHaveBeenCalledWith(result.sessionId, "candidate_2");
  });

  it("marks candidate results busy and prevents duplicate selection requests", async () => {
    let resolveSelection: ((value: SelectCandidateResult) => void) | undefined;
    const pendingSelection = new Promise<SelectCandidateResult>((resolve) => {
      resolveSelection = resolve;
    });
    render(
      <GoalEntry
        api={createApiClient(
          vi.fn().mockResolvedValue(result),
          vi.fn().mockReturnValue(pendingSelection),
        )}
      />,
    );

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));
    const cards = await screen.findAllByRole("article");
    const firstCard = cards[0];
    if (firstCard === undefined) {
      throw new Error("Expected first candidate card");
    }
    fireEvent.click(within(firstCard).getByRole("button", { name: "Select this project" }));

    expect(
      screen.getByRole("heading", { name: "Compare project candidates" }).closest("section"),
    ).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(/turning the selected candidate/i)).toHaveAttribute("role", "status");
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }

    resolveSelection?.(selectionResult(result.candidates[0]));
    expect(await screen.findByText("Project brief is ready.")).toHaveAttribute("role", "status");
  });

  it("restores a retryable selection control when brief generation fails", async () => {
    render(
      <GoalEntry
        api={createApiClient(
          vi.fn().mockResolvedValue(result),
          vi.fn().mockRejectedValue(new Error("provider diagnostic")),
        )}
      />,
    );

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "Learn compiler backends" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));
    const cards = await screen.findAllByRole("article");
    const firstCard = cards[0];
    if (firstCard === undefined) {
      throw new Error("Expected first candidate card");
    }
    fireEvent.click(within(firstCard).getByRole("button", { name: "Select this project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The project brief could not be created. Try selecting the project again.",
    );
    expect(within(firstCard).getByRole("button", { name: "Select this project" })).toBeEnabled();
    expect(screen.queryByText("provider diagnostic")).not.toBeInTheDocument();
  });
});
