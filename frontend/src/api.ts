import type { AuthClient } from "./auth";

export interface EvidenceCitation {
  evidence_id: string;
  generated_connection: string;
}

export interface ProjectCandidate {
  estimated_scope: "multi-month" | "multi-week" | "weekend";
  evidence_citations: EvidenceCitation[];
  first_milestone: string;
  rationale: string;
  summary: string;
  technologies: string[];
  title: string;
}

export interface CreateSessionResult {
  candidates: [ProjectCandidate, ProjectCandidate, ProjectCandidate];
  sessionId: string;
}

export interface ApiClient {
  createSession(goal: string): Promise<CreateSessionResult>;
}

export interface ApiConfiguration {
  baseUrl: string;
}

type RequestFunction = (input: string, init: RequestInit) => Promise<Response>;

const SESSION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EVIDENCE_ID_PATTERN = /^(book|byte|museum|project):[0-9a-f]{16}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isEvidenceCitation(value: unknown): value is EvidenceCitation {
  return (
    isRecord(value) &&
    isNonEmptyString(value.evidence_id) &&
    EVIDENCE_ID_PATTERN.test(value.evidence_id) &&
    isNonEmptyString(value.generated_connection)
  );
}

function isProjectCandidate(value: unknown): value is ProjectCandidate {
  return (
    isRecord(value) &&
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

function parseCreateSessionResponse(value: unknown): CreateSessionResult {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error("Invalid API response envelope");
  }

  const { candidates, sessionId } = value.data;
  if (
    !isNonEmptyString(sessionId) ||
    !SESSION_ID_PATTERN.test(sessionId) ||
    !isCandidateTuple(candidates)
  ) {
    throw new Error("Invalid create-session response");
  }

  return {
    candidates,
    sessionId,
  };
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
        throw new Error(`API request failed with status ${response.status.toString()}`);
      }
      return parseCreateSessionResponse(await response.json());
    },
  };
}
