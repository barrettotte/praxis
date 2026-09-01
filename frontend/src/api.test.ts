import { describe, expect, it, vi } from "vitest";

import { createApiClient, readApiConfiguration } from "./api";
import type { AuthClient } from "./auth";

const validResponse = {
  data: {
    candidates: [1, 2, 3].map((number) => ({
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
  it("sends an authenticated create-session request and validates the response", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("access-token");
    const request = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validResponse), {
        headers: { "content-type": "application/json" },
        status: 201,
      }),
    );
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(getAccessToken),
      request,
    );

    await expect(client.createSession("Learn compiler backends")).resolves.toEqual(
      validResponse.data,
    );
    expect(getAccessToken).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledWith("https://api.example.com/v1/sessions", {
      body: JSON.stringify({ goal: "Learn compiler backends" }),
      credentials: "omit",
      headers: {
        authorization: "Bearer access-token",
        "content-type": "application/json",
      },
      method: "POST",
    });
  });

  it("rejects malformed success responses", async () => {
    const request = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { candidates: [], sessionId: "invalid" } }), {
        status: 201,
      }),
    );
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
    );

    await expect(client.createSession("Learn compiler backends")).rejects.toThrow(
      "Invalid create-session response",
    );
  });

  it("rejects candidate citations that do not resolve to returned evidence", async () => {
    const malformedResponse = structuredClone(validResponse);
    const evidence = malformedResponse.data.evidence[0];
    if (evidence === undefined) {
      throw new Error("Expected evidence fixture");
    }
    evidence.evidence_id = "book:0000000000000001";
    const request = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(malformedResponse), { status: 201 }));
    const client = createApiClient(
      { baseUrl: "https://api.example.com" },
      createAuthClient(),
      request,
    );

    await expect(client.createSession("Learn compiler backends")).rejects.toThrow(
      "Invalid create-session response",
    );
  });
});
