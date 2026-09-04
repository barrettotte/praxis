import { useState, type SyntheticEvent } from "react";

import { CandidateCards } from "./CandidateCards";
import { ProjectBriefView } from "./ProjectBriefView";
import type { ApiClient, CreateSessionResult, SelectCandidateResult } from "./api";

const GOAL_MAX_LENGTH = 4_000;
const GOAL_REQUIRED_ERROR = "Describe what you want to learn or build.";

interface GoalEntryProps {
  api: ApiClient;
}

type RequestState = "complete" | "failed" | "ready" | "working";
type SelectionState = "complete" | "failed" | "ready" | "working";

export function GoalEntry({ api }: GoalEntryProps) {
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateSessionResult | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("ready");
  const [selectedCandidateIndex, setSelectedCandidateIndex] = useState<number | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [selectionResult, setSelectionResult] = useState<SelectCandidateResult | null>(null);
  const [selectionState, setSelectionState] = useState<SelectionState>("ready");
  const interactionBusy = requestState === "working" || selectionState === "working";

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedGoal = goal.trim();
    if (normalizedGoal === "") {
      setError(GOAL_REQUIRED_ERROR);
      setRequestState("ready");
      return;
    }

    setGoal(normalizedGoal);
    setError(null);
    setResult(null);
    setSelectedCandidateIndex(null);
    setSelectionError(null);
    setSelectionResult(null);
    setSelectionState("ready");
    setRequestState("working");
    try {
      setResult(await api.createSession(normalizedGoal));
      setRequestState("complete");
    } catch {
      setResult(null);
      setError("Recommendations could not be created. Try again.");
      setRequestState("failed");
    }
  }

  async function handleCandidateSelect(index: number) {
    if (result === null) {
      return;
    }
    const candidate = result.candidates[index];
    if (candidate === undefined) {
      return;
    }
    setSelectedCandidateIndex(index);
    setSelectionError(null);
    setSelectionResult(null);
    setSelectionState("working");
    try {
      setSelectionResult(await api.selectCandidate(result.sessionId, candidate.candidateId));
      setSelectionState("complete");
    } catch {
      setSelectedCandidateIndex(null);
      setSelectionError("The project brief could not be created. Try selecting the project again.");
      setSelectionState("failed");
    }
  }

  return (
    <section className="goal-entry" aria-labelledby="goal-heading">
      <div className="goal-entry-heading">
        <p className="eyebrow">Project goal</p>
        <h2 id="goal-heading">What would you like to explore?</h2>
        <p className="goal-introduction">
          Include a skill, topic, time budget, or constraint. Praxis will connect it to your
          personal evidence.
        </p>
      </div>
      <form
        className="goal-form"
        aria-busy={interactionBusy}
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
      >
        <label htmlFor="goal">Goal or interest</label>
        <textarea
          id="goal"
          name="goal"
          maxLength={GOAL_MAX_LENGTH}
          rows={6}
          disabled={interactionBusy}
          required
          value={goal}
          aria-describedby={error === null ? "goal-help" : "goal-help goal-error"}
          aria-invalid={error === GOAL_REQUIRED_ERROR}
          onChange={(event) => {
            setGoal(event.target.value);
            setError(null);
            setResult(null);
            setSelectedCandidateIndex(null);
            setSelectionError(null);
            setSelectionResult(null);
            setSelectionState("ready");
            setRequestState("ready");
          }}
        />
        <p id="goal-help" className="form-help">
          {goal.length.toLocaleString()} of {GOAL_MAX_LENGTH.toLocaleString()} characters
        </p>
        {error === null ? null : (
          <p id="goal-error" className="form-error" role="alert">
            {error}
          </p>
        )}
        {requestState === "working" ? (
          <p className="agent-progress" role="status" aria-live="polite">
            Praxis is searching your evidence and preparing three candidates…
          </p>
        ) : null}
        {requestState === "complete" ? (
          <p className="form-success" role="status">
            Three candidates are ready.
          </p>
        ) : null}
        <button className="button" type="submit" disabled={interactionBusy}>
          {requestState === "working" ? "Finding projects…" : "Find project ideas"}
        </button>
      </form>
      {result === null ? null : (
        <CandidateCards
          candidates={result.candidates}
          evidence={result.evidence}
          selectedCandidateIndex={selectedCandidateIndex}
          selectionPending={selectionState === "working"}
          onSelect={(index) => {
            void handleCandidateSelect(index);
          }}
        />
      )}
      {selectionState === "working" ? (
        <p className="brief-status" role="status">
          Praxis is turning the selected candidate into a project brief…
        </p>
      ) : null}
      {selectionError === null ? null : (
        <p className="form-error brief-status" role="alert">
          {selectionError}
        </p>
      )}
      {selectionState === "complete" && selectionResult !== null ? (
        <p className="form-success brief-status" role="status">
          Project brief is ready.
        </p>
      ) : null}
      {selectionResult === null ? null : <ProjectBriefView result={selectionResult} />}
    </section>
  );
}
