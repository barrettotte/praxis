import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  configure: vi.fn(),
  confirmSignIn: vi.fn(),
  fetchAuthSession: vi.fn(),
  getCurrentUser: vi.fn(),
  setKeyValueStorage: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("aws-amplify", () => ({ Amplify: { configure: mocks.configure } }));
vi.mock("aws-amplify/auth", () => ({
  confirmSignIn: mocks.confirmSignIn,
  fetchAuthSession: mocks.fetchAuthSession,
  getCurrentUser: mocks.getCurrentUser,
  signIn: mocks.signIn,
  signOut: mocks.signOut,
}));
vi.mock("aws-amplify/auth/cognito", () => ({
  cognitoUserPoolsTokenProvider: { setKeyValueStorage: mocks.setKeyValueStorage },
}));
vi.mock("aws-amplify/utils", () => ({ sessionStorage: { name: "session-storage" } }));

import { createCognitoAuthClient, readAuthConfiguration } from "./auth";

const configuration = {
  userPoolClientId: "browser-client",
  userPoolId: "us-east-1_pool",
};

describe("Cognito auth client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requires both public Cognito identifiers", () => {
    expect(() => readAuthConfiguration({})).toThrow("VITE_COGNITO_CLIENT_ID is required");
    expect(
      readAuthConfiguration({
        VITE_COGNITO_CLIENT_ID: " browser-client ",
        VITE_COGNITO_USER_POOL_ID: " us-east-1_pool ",
      }),
    ).toEqual(configuration);
  });

  it("configures Cognito with tab-scoped token storage", () => {
    createCognitoAuthClient(configuration);

    expect(mocks.configure).toHaveBeenCalledWith({
      Auth: { Cognito: configuration },
    });
    expect(mocks.setKeyValueStorage).toHaveBeenCalledWith({ name: "session-storage" });
  });

  it("maps the temporary-password challenge", async () => {
    mocks.signIn.mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED" },
    });
    const auth = createCognitoAuthClient(configuration);

    await expect(auth.signIn("person@example.com", "password")).resolves.toBe(
      "new_password_required",
    );
  });

  it("returns the current access token for authenticated API requests", async () => {
    mocks.fetchAuthSession.mockResolvedValue({
      tokens: { accessToken: { toString: () => "access-token" } },
    });
    const auth = createCognitoAuthClient(configuration);

    await expect(auth.getAccessToken()).resolves.toBe("access-token");
  });
});
