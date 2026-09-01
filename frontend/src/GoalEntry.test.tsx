import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GoalEntry } from "./GoalEntry";
import type { ApiClient, CreateSessionResult, ProjectCandidate } from "./api";

const candidate: ProjectCandidate = {
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
  candidates: [candidate, candidate, candidate],
  sessionId: "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
};

function createApiClient(createSession = vi.fn().mockResolvedValue(result)): ApiClient {
  return { createSession };
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
  });

  it("rejects a goal containing only whitespace", () => {
    const createSession = vi.fn();
    render(<GoalEntry api={createApiClient(createSession)} />);

    fireEvent.change(screen.getByLabelText("Goal or interest"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find project ideas" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Describe what you want to learn or build.",
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
    expect(screen.getByRole("button", { name: "Finding projects…" })).toBeDisabled();

    resolveRequest?.(result);
    expect(await screen.findByText("Three candidates are ready.")).toHaveAttribute(
      "role",
      "status",
    );
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
});
