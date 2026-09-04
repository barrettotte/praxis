import type { AuthClient } from "./auth";

export interface EvidenceCitation {
  evidence_id: string;
  generated_connection: string;
}

export interface ProjectCandidate {
  candidateId: `candidate_${1 | 2 | 3}`;
  estimated_scope: "multi-month" | "multi-week" | "weekend";
  evidence_citations: EvidenceCitation[];
  first_milestone: string;
  rationale: string;
  summary: string;
  technologies: string[];
  title: string;
}

export interface ProjectMilestone {
  deliverable: string;
  title: string;
  verification: string;
}

export interface ProjectRisk {
  mitigation: string;
  risk: string;
}

export interface ProjectAcceptanceCriterion {
  criterion: string;
  verification: string;
}

export interface ProjectBrief {
  acceptance_criteria: ProjectAcceptanceCriterion[];
  assumptions: string[];
  deliverables: string[];
  milestones: ProjectMilestone[];
  objective: string;
  out_of_scope: string[];
  risks: ProjectRisk[];
  scope: string;
  technical_approach: string[];
}

interface EvidenceRecord {
  evidence_id: string;
}

export interface BookEvidence extends EvidenceRecord {
  author: string | null;
  category: string | null;
  kind: "book";
  tags: string[];
  title: string;
  year: number;
}

export interface ProjectEvidence extends EvidenceRecord {
  date: string | null;
  description: string;
  kind: "project";
  languages: string[];
  name: string;
}

export interface ByteEvidence extends EvidenceRecord {
  category: string;
  date: string;
  kind: "byte";
  name: string;
}

export interface MuseumEvidence extends EvidenceRecord {
  category: string;
  description: string;
  kind: "museum";
  manufacturer: string;
  name: string;
  year: number | null;
}

export type SupportingEvidence = BookEvidence | ByteEvidence | MuseumEvidence | ProjectEvidence;

export interface CreateSessionResult {
  candidates: [ProjectCandidate, ProjectCandidate, ProjectCandidate];
  evidence: SupportingEvidence[];
  sessionId: string;
}

export interface SelectCandidateResult {
  brief: ProjectBrief;
  candidate: ProjectCandidate;
  candidateId: ProjectCandidate["candidateId"];
  evidence: SupportingEvidence[];
  sessionId: string;
}

export interface ApiClient {
  createSession(goal: string): Promise<CreateSessionResult>;
  selectCandidate(
    sessionId: string,
    candidateId: ProjectCandidate["candidateId"],
  ): Promise<SelectCandidateResult>;
}

export interface ApiConfiguration {
  baseUrl: string;
}

export class SensitiveInputError extends Error {
  constructor() {
    super("Remove passwords, API keys, or tokens from your goal.");
  }
}

type RequestFunction = (input: string, init: RequestInit) => Promise<Response>;
type WaitFunction = (milliseconds: number) => Promise<void>;

interface PendingSessionResult {
  sessionId: string;
  status: "pending";
}

type SessionPollResult =
  | { sessionId: string; status: "failed" | "pending" }
  | { result: CreateSessionResult; status: "ready" };

const SESSION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EVIDENCE_ID_PATTERN = /^(book|byte|museum|project):[0-9a-f]{16}$/;
const CANDIDATE_ID_PATTERN = /^candidate_[1-3]$/;
const SESSION_POLL_INTERVAL_MS = 2_000;
const SESSION_POLL_ATTEMPTS = 60;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isEvidenceCitation(value: unknown): value is EvidenceCitation {
  return (
    isRecord(value) &&
    isNonEmptyString(value.evidence_id) &&
    EVIDENCE_ID_PATTERN.test(value.evidence_id) &&
    isNonEmptyString(value.generated_connection)
  );
}

function isProjectMilestone(value: unknown): value is ProjectMilestone {
  return (
    isRecord(value) &&
    isNonEmptyString(value.title) &&
    isNonEmptyString(value.deliverable) &&
    isNonEmptyString(value.verification)
  );
}

function isProjectRisk(value: unknown): value is ProjectRisk {
  return isRecord(value) && isNonEmptyString(value.risk) && isNonEmptyString(value.mitigation);
}

function isProjectAcceptanceCriterion(value: unknown): value is ProjectAcceptanceCriterion {
  return (
    isRecord(value) && isNonEmptyString(value.criterion) && isNonEmptyString(value.verification)
  );
}

function isBoundedList<T>(
  value: unknown,
  minimum: number,
  maximum: number,
  predicate: (item: unknown) => item is T,
): value is T[] {
  return (
    Array.isArray(value) &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.every(predicate)
  );
}

function isProjectBrief(value: unknown): value is ProjectBrief {
  return (
    isRecord(value) &&
    isNonEmptyString(value.objective) &&
    isNonEmptyString(value.scope) &&
    isBoundedList(value.technical_approach, 3, 6, isNonEmptyString) &&
    isBoundedList(value.assumptions, 2, 5, isNonEmptyString) &&
    isBoundedList(value.out_of_scope, 2, 5, isNonEmptyString) &&
    isBoundedList(value.deliverables, 2, 6, isNonEmptyString) &&
    isBoundedList(value.milestones, 3, 5, isProjectMilestone) &&
    isBoundedList(value.risks, 2, 4, isProjectRisk) &&
    isBoundedList(value.acceptance_criteria, 3, 6, isProjectAcceptanceCriterion)
  );
}

function isProjectCandidate(value: unknown): value is ProjectCandidate {
  return (
    isRecord(value) &&
    isNonEmptyString(value.candidateId) &&
    CANDIDATE_ID_PATTERN.test(value.candidateId) &&
    isNonEmptyString(value.title) &&
    isNonEmptyString(value.summary) &&
    isNonEmptyString(value.rationale) &&
    (value.estimated_scope === "weekend" ||
      value.estimated_scope === "multi-week" ||
      value.estimated_scope === "multi-month") &&
    Array.isArray(value.technologies) &&
    value.technologies.length > 0 &&
    value.technologies.every(isNonEmptyString) &&
    isNonEmptyString(value.first_milestone) &&
    Array.isArray(value.evidence_citations) &&
    value.evidence_citations.length > 0 &&
    value.evidence_citations.every(isEvidenceCitation)
  );
}

function isCandidateTuple(
  value: unknown,
): value is [ProjectCandidate, ProjectCandidate, ProjectCandidate] {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    isProjectCandidate(value[0]) &&
    isProjectCandidate(value[1]) &&
    isProjectCandidate(value[2])
  );
}

function hasEvidenceIdentity(
  value: Record<string, unknown>,
  kind: SupportingEvidence["kind"],
): boolean {
  return (
    value.kind === kind &&
    isNonEmptyString(value.evidence_id) &&
    EVIDENCE_ID_PATTERN.test(value.evidence_id) &&
    value.evidence_id.startsWith(`${kind}:`)
  );
}

function isSupportingEvidence(value: unknown): value is SupportingEvidence {
  if (!isRecord(value) || typeof value.kind !== "string") {
    return false;
  }
  switch (value.kind) {
    case "book":
      return (
        hasEvidenceIdentity(value, "book") &&
        isNonEmptyString(value.title) &&
        isNullableString(value.author) &&
        typeof value.year === "number" &&
        Number.isInteger(value.year) &&
        value.year >= 0 &&
        isNullableString(value.category) &&
        isStringArray(value.tags)
      );
    case "project":
      return (
        hasEvidenceIdentity(value, "project") &&
        isNonEmptyString(value.name) &&
        isNonEmptyString(value.description) &&
        isNullableString(value.date) &&
        isStringArray(value.languages)
      );
    case "byte":
      return (
        hasEvidenceIdentity(value, "byte") &&
        isNonEmptyString(value.name) &&
        isNonEmptyString(value.category) &&
        isNonEmptyString(value.date)
      );
    case "museum":
      return (
        hasEvidenceIdentity(value, "museum") &&
        isNonEmptyString(value.name) &&
        isNonEmptyString(value.manufacturer) &&
        (value.year === null ||
          (typeof value.year === "number" && Number.isInteger(value.year) && value.year >= 0)) &&
        isNonEmptyString(value.category) &&
        isNonEmptyString(value.description)
      );
    default:
      return false;
  }
}

function isSupportingEvidenceList(value: unknown): value is SupportingEvidence[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 3) {
    return false;
  }
  if (!value.every(isSupportingEvidence)) {
    return false;
  }
  const evidenceIds = value.map((item) => item.evidence_id);
  return new Set(evidenceIds).size === evidenceIds.length;
}

function parseCreateSessionResponse(value: unknown): CreateSessionResult {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error("Invalid API response envelope");
  }

  const { candidates, evidence, sessionId } = value.data;
  if (
    !isNonEmptyString(sessionId) ||
    !SESSION_ID_PATTERN.test(sessionId) ||
    !isCandidateTuple(candidates) ||
    !isSupportingEvidenceList(evidence)
  ) {
    throw new Error("Invalid create-session response");
  }

  const evidenceIds = new Set(evidence.map((item) => item.evidence_id));
  if (
    candidates.some((candidate) =>
      candidate.evidence_citations.some((citation) => !evidenceIds.has(citation.evidence_id)),
    )
  ) {
    throw new Error("Invalid create-session response");
  }

  return {
    candidates,
    evidence,
    sessionId,
  };
}

function parsePendingSessionResponse(value: unknown): PendingSessionResult {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error("Invalid API response envelope");
  }
  const { sessionId, status } = value.data;
  if (!isNonEmptyString(sessionId) || !SESSION_ID_PATTERN.test(sessionId) || status !== "pending") {
    throw new Error("Invalid pending-session response");
  }
  return { sessionId, status };
}

function parseSessionStatusResponse(value: unknown): SessionPollResult {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error("Invalid API response envelope");
  }
  const { sessionId, status } = value.data;
  if (!isNonEmptyString(sessionId) || !SESSION_ID_PATTERN.test(sessionId)) {
    throw new Error("Invalid session-status response");
  }
  if (status === "failed" || status === "pending") {
    return { sessionId, status };
  }
  if (status !== "ready") {
    throw new Error("Invalid session-status response");
  }
  return { result: parseCreateSessionResponse(value), status };
}

function parseSelectCandidateResponse(value: unknown): SelectCandidateResult {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error("Invalid API response envelope");
  }
  const { brief, candidate, candidateId, evidence, sessionId } = value.data;
  if (
    !isNonEmptyString(sessionId) ||
    !SESSION_ID_PATTERN.test(sessionId) ||
    !isNonEmptyString(candidateId) ||
    !CANDIDATE_ID_PATTERN.test(candidateId) ||
    !isProjectCandidate(candidate) ||
    candidate.candidateId !== candidateId ||
    !isProjectBrief(brief) ||
    !isSupportingEvidenceList(evidence)
  ) {
    throw new Error("Invalid select-candidate response");
  }
  const evidenceIds = new Set(evidence.map((item) => item.evidence_id));
  if (candidate.evidence_citations.some((citation) => !evidenceIds.has(citation.evidence_id))) {
    throw new Error("Invalid select-candidate response");
  }
  return { brief, candidate, candidateId, evidence, sessionId };
}

export function readApiConfiguration(environment: Record<string, unknown>): ApiConfiguration {
  const value = environment.VITE_API_URL;
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error("VITE_API_URL is required");
  }

  const url = new URL(value.trim());
  if (url.protocol !== "https:" && !(url.protocol === "http:" && url.hostname === "localhost")) {
    throw new Error("VITE_API_URL must use HTTPS or HTTP localhost");
  }
  url.pathname = url.pathname.replace(/\/$/, "");
  return { baseUrl: url.toString().replace(/\/$/, "") };
}

export function createApiClient(
  configuration: ApiConfiguration,
  auth: AuthClient,
  request: RequestFunction = globalThis.fetch,
  wait: WaitFunction = (milliseconds) =>
    new Promise((resolve) => {
      globalThis.setTimeout(resolve, milliseconds);
    }),
): ApiClient {
  return {
    async createSession(goal) {
      const accessToken = await auth.getAccessToken();
      const response = await request(`${configuration.baseUrl}/v1/sessions`, {
        body: JSON.stringify({ goal }),
        credentials: "omit",
        headers: {
          authorization: `Bearer ${accessToken}`,
          "content-type": "application/json",
        },
        method: "POST",
      });
      if (!response.ok) {
        if (response.status === 400) {
          const errorBody: unknown = await response.json().catch(() => null);
          if (
            isRecord(errorBody) &&
            isRecord(errorBody.error) &&
            errorBody.error.code === "sensitive_input"
          ) {
            throw new SensitiveInputError();
          }
        }
        throw new Error(`API request failed with status ${response.status.toString()}`);
      }
      const pending = parsePendingSessionResponse(await response.json());
      for (let attempt = 0; attempt < SESSION_POLL_ATTEMPTS; attempt += 1) {
        await wait(SESSION_POLL_INTERVAL_MS);
        const statusResponse = await request(
          `${configuration.baseUrl}/v1/sessions/${pending.sessionId}`,
          {
            credentials: "omit",
            headers: { authorization: `Bearer ${accessToken}` },
            method: "GET",
          },
        );
        if (!statusResponse.ok) {
          throw new Error(`API request failed with status ${statusResponse.status.toString()}`);
        }
        const status = parseSessionStatusResponse(await statusResponse.json());
        if (status.status === "ready") {
          return status.result;
        }
        if (status.status === "failed") {
          throw new Error("Recommendation session failed");
        }
      }
      throw new Error("Recommendation session timed out");
    },
    async selectCandidate(sessionId, candidateId) {
      const accessToken = await auth.getAccessToken();
      const response = await request(`${configuration.baseUrl}/v1/projects/${candidateId}/select`, {
        body: JSON.stringify({ sessionId }),
        credentials: "omit",
        headers: {
          authorization: `Bearer ${accessToken}`,
          "content-type": "application/json",
        },
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`API request failed with status ${response.status.toString()}`);
      }
      return parseSelectCandidateResponse(await response.json());
    },
  };
}
