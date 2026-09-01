import { useState, type SyntheticEvent } from "react";

import { CandidateCards } from "./CandidateCards";
import type { ApiClient, CreateSessionResult } from "./api";

const GOAL_MAX_LENGTH = 4_000;

interface GoalEntryProps {
  api: ApiClient;
}

type RequestState = "complete" | "failed" | "ready" | "working";

export function GoalEntry({ api }: GoalEntryProps) {
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateSessionResult | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("ready");

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedGoal = goal.trim();
    if (normalizedGoal === "") {
      setError("Describe what you want to learn or build.");
      setRequestState("ready");
      return;
    }

    setGoal(normalizedGoal);
    setError(null);
    setResult(null);
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
        aria-busy={requestState === "working"}
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
          disabled={requestState === "working"}
          required
          value={goal}
          aria-describedby="goal-help"
          onChange={(event) => {
            setGoal(event.target.value);
            setError(null);
            setResult(null);
            setRequestState("ready");
          }}
        />
        <p id="goal-help" className="form-help">
          {goal.length.toLocaleString()} of {GOAL_MAX_LENGTH.toLocaleString()} characters
        </p>
        {error === null ? null : (
          <p className="form-error" role="alert">
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
        <button className="button" type="submit" disabled={requestState === "working"}>
          {requestState === "working" ? "Finding projects…" : "Find project ideas"}
        </button>
      </form>
      {result === null ? null : (
        <CandidateCards candidates={result.candidates} evidence={result.evidence} />
      )}
    </section>
  );
}
