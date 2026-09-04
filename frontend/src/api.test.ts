import { describe, expect, it, vi } from "vitest";

import { createApiClient, readApiConfiguration, SensitiveInputError } from "./api";
import type { AuthClient } from "./auth";

const validResponse = {
  data: {
    candidates: [1, 2, 3].map((number) => ({
      candidateId: `candidate_${number.toString()}`,
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
      title: `Compiler backend exercise ${number.toString()}`,
    })),
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
  },
};

const validSelectionResponse = {
  data: {
    brief: {
      acceptance_criteria: [1, 2, 3].map((number) => ({
        criterion: `Criterion ${number.toString()} has a measurable result.`,
        verification: `Verification method ${number.toString()}.`,
      })),
      assumptions: ["Python is available.", "A local test runner is available."],
      deliverables: ["A documented input model.", "A tested instruction selector."],
      milestones: [1, 2, 3].map((number) => ({
        deliverable: `Deliverable ${number.toString()}`,
        title: `Milestone ${number.toString()}`,
        verification: `Milestone verification ${number.toString()}`,
      })),
      objective: "Build a compact compiler backend.",
      out_of_scope: ["Register allocation.", "Multiple target architectures."],
      risks: [1, 2].map((number) => ({
        mitigation: `Mitigation ${number.toString()}`,
        risk: `Risk ${number.toString()}`,
      })),
      scope: "Implement one expression-lowering path.",
      technical_approach: [
        "Define a JSON expression model and validate sample inputs.",
        "Lower each expression into a target-instruction list.",
        "Execute the instruction list and compare its numeric result.",
      ],
    },
    candidate: validResponse.data.candidates[1],
    candidateId: "candidate_2",
    evidence: validResponse.data.evidence,
    sessionId: validResponse.data.sessionId,
  },
};

const pendingResponse = {
  data: {
    sessionId: validResponse.data.sessionId,
    status: "pending",
  },
};

const readyResponse = {
  data: {
    ...validResponse.data,
    status: "ready",
  },
};

function createAuthClient(getAccessToken = vi.fn().mockResolvedValue("access-token")): AuthClient {
  return {
    confirmNewPassword: vi.fn(),
    getAccessToken,
    restoreSession: vi.fn(),
    signIn: vi.fn(),
    signOut: vi.fn(),
  };
}

describe("readApiConfiguration", () => {
  it("normalizes the configured deployment URL", () => {
    expect(
      readApiConfiguration({
        VITE_API_URL: "https://example.execute-api.us-east-1.amazonaws.com/",
      }),
    ).toEqual({ baseUrl: "https://example.execute-api.us-east-1.amazonaws.com" });
  });

  it("rejects missing and insecure remote URLs", () => {
    expect(() => readApiConfiguration({})).toThrow("VITE_API_URL is required");
    expect(() => readApiConfiguration({ VITE_API_URL: "http://example.com" })).toThrow(
      "VITE_API_URL must use HTTPS or HTTP localhost",
    );
  });
});

describe("createApiClient", () => {
  it("maps credential rejection to a fixed message without polling or reflecting server text", async () => {
    const request = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "sensitive_input", message: "do-not-reflect" } }),
        {
          status: 400,
        },
      ),
    );
    const wait = vi.fn();
    const client = createApiClient(
      { baseUrl: "https://example.com" },
      createAuthClient(),
      request,
      wait,
    );

    await expect(client.createSession("synthetic goal")).rejects.toEqual(new SensitiveInputError());
    expect(request).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
  });

  it.each(["not json", JSON.stringify({ error: { code: "unknown", message: "do-not-reflect" } })])(
    "keeps other 400 responses generic: %s",
    async (body) => {
      const request = vi.fn().mockResolvedValue(new Response(body, { status: 400 }));
      const client = createApiClient(
        { baseUrl: "https://example.com" },
        createAuthClient(),
        request,
      );
      await expect(client.createSession("compiler")).rejects.toThrow(
        "API request failed with status 400",
      );
    },
  );

  it("stops polling a session that stays pending", async () => {
    const request = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response(JSON.stringify(pendingResponse), { status: 202 })),
      );
    const wait = vi.fn().mockResolvedValue(undefined);
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
      wait,
    );

    await expect(client.createSession("compiler")).rejects.toThrow("session timed out");
    expect(request).toHaveBeenCalledTimes(61);
    expect(wait).toHaveBeenCalledTimes(60);
  });

  it.each(["create", "select"])(
    "does not automatically retry a throttled %s request",
    async (operation) => {
      const request = vi.fn().mockResolvedValue(new Response("sensitive detail", { status: 429 }));
      const client = createApiClient(
        { baseUrl: "https://api.example.com" },
        createAuthClient(),
        request,
      );

      const result =
        operation === "create"
          ? client.createSession("compiler")
          : client.selectCandidate(validResponse.data.sessionId, "candidate_1");
      await expect(result).rejects.toThrow("API request failed with status 429");
      expect(request).toHaveBeenCalledOnce();
    },
  );

  it("starts and polls an authenticated session until candidates are ready", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("access-token");
    const request = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pendingResponse), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(pendingResponse), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(readyResponse), { status: 200 }));
    const wait = vi.fn().mockResolvedValue(undefined);
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(getAccessToken),
      request,
      wait,
    );

    await expect(client.createSession("Learn compiler backends")).resolves.toEqual(
      validResponse.data,
    );
    expect(getAccessToken).toHaveBeenCalledOnce();
    expect(request).toHaveBeenNthCalledWith(1, "https://api.example.com/v1/sessions", {
      body: JSON.stringify({ goal: "Learn compiler backends" }),
      credentials: "omit",
      headers: {
        authorization: "Bearer access-token",
        "content-type": "application/json",
      },
      method: "POST",
    });
    expect(request).toHaveBeenNthCalledWith(
      2,
      `https://api.example.com/v1/sessions/${validResponse.data.sessionId}`,
      {
        credentials: "omit",
        headers: { authorization: "Bearer access-token" },
        method: "GET",
      },
    );
    expect(request).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenCalledTimes(2);
  });

  it("rejects malformed success responses", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pendingResponse), { status: 202 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { candidates: [], sessionId: "invalid" } }), {
          status: 200,
        }),
      );
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
      vi.fn().mockResolvedValue(undefined),
    );

    await expect(client.createSession("Learn compiler backends")).rejects.toThrow(
      "Invalid session-status response",
    );
  });

  it("rejects candidate citations that do not resolve to returned evidence", async () => {
    const malformedResponse = structuredClone(readyResponse);
    const evidence = malformedResponse.data.evidence[0];
    if (evidence === undefined) {
      throw new Error("Expected evidence fixture");
    }
    evidence.evidence_id = "book:0000000000000001";
    const request = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pendingResponse), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(malformedResponse), { status: 200 }));
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
      vi.fn().mockResolvedValue(undefined),
    );

    await expect(client.createSession("Learn compiler backends")).rejects.toThrow(
      "Invalid create-session response",
    );
  });

  it("rejects a safely failed background session", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(pendingResponse), { status: 202 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { sessionId: validResponse.data.sessionId, status: "failed" },
          }),
          { status: 200 },
        ),
      );
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
      vi.fn().mockResolvedValue(undefined),
    );

    await expect(client.createSession("Learn compiler backends")).rejects.toThrow(
      "Recommendation session failed",
    );
  });

  it("sends an authenticated selection request and validates the project brief", async () => {
    const request = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(validSelectionResponse), { status: 200 }));
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
    );

    await expect(
      client.selectCandidate(validResponse.data.sessionId, "candidate_2"),
    ).resolves.toEqual(validSelectionResponse.data);
    expect(request).toHaveBeenCalledWith("https://api.example.com/v1/projects/candidate_2/select", {
      body: JSON.stringify({ sessionId: validResponse.data.sessionId }),
      credentials: "omit",
      headers: {
        authorization: "Bearer access-token",
        "content-type": "application/json",
      },
      method: "POST",
    });
  });

  it("rejects a malformed project brief response", async () => {
    const malformedResponse = structuredClone(validSelectionResponse);
    malformedResponse.data.brief.milestones = [];
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(malformedResponse), {
          status: 200,
        }),
      ),
    );

    await expect(
      client.selectCandidate(validResponse.data.sessionId, "candidate_2"),
    ).rejects.toThrow("Invalid select-candidate response");
  });
});
