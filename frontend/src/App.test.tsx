import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";

function createAuthClient(overrides: Partial<AuthClient> = {}): AuthClient {
  return {
    confirmNewPassword: vi.fn().mockResolvedValue(undefined),
    getAccessToken: vi.fn().mockResolvedValue("access-token"),
    restoreSession: vi.fn().mockResolvedValue(false),
    signIn: vi.fn().mockResolvedValue("signed_in"),
    signOut: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

async function enterCredentials() {
  fireEvent.change(await screen.findByLabelText("Email"), {
    target: { value: "person@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "TemporaryPassword1!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("App", () => {
  it("introduces the workflow and presents an accessible sign-in form", async () => {
    render(<App auth={createAuthClient()} />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Choose what to build next." }),
    ).toBeVisible();
    expect(screen.getByText(/personal evidence/i)).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Sign in to Praxis." })).toBeVisible();
    expect(screen.getByLabelText("Email")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });

  it("signs in with email and password", async () => {
    const signIn = vi.fn().mockResolvedValue("signed_in");
    const auth = createAuthClient({ signIn });
    render(<App auth={auth} />);

    await enterCredentials();

    expect(await screen.findByRole("heading", { name: "You’re signed in." })).toBeVisible();
    expect(signIn).toHaveBeenCalledWith("person@example.com", "TemporaryPassword1!");
  });

  it("completes the required-new-password challenge", async () => {
    const confirmNewPassword = vi.fn().mockResolvedValue(undefined);
    const auth = createAuthClient({
      confirmNewPassword,
      signIn: vi.fn().mockResolvedValue("new_password_required"),
    });
    render(<App auth={auth} />);
    await enterCredentials();

    expect(
      await screen.findByRole("heading", { name: "Choose a permanent password." }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "PermanentPassword1!" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "PermanentPassword1!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    expect(await screen.findByRole("heading", { name: "You’re signed in." })).toBeVisible();
    expect(confirmNewPassword).toHaveBeenCalledWith("PermanentPassword1!");
  });

  it("restores and signs out an existing session", async () => {
    const signOut = vi.fn().mockResolvedValue(undefined);
    const auth = createAuthClient({
      restoreSession: vi.fn().mockResolvedValue(true),
      signOut,
    });
    render(<App auth={auth} />);

    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("button", { name: "Sign in" })).toBeVisible();
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("does not expose authentication error details", async () => {
    const auth = createAuthClient({
      signIn: vi.fn().mockRejectedValue(new Error("User does not exist")),
    });
    render(<App auth={auth} />);
    await enterCredentials();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign-in failed. Check your credentials and try again.",
    );
    expect(screen.queryByText("User does not exist")).not.toBeInTheDocument();
  });
});
