import { useEffect, useState, type ReactNode, type SyntheticEvent } from "react";

import type { AuthClient } from "./auth";

type AuthView = "checking" | "new_password" | "signed_in" | "signed_out";

interface AuthPanelProps {
  auth: AuthClient;
  children: ReactNode;
}

export function AuthPanel({ auth, children }: AuthPanelProps) {
  const [view, setView] = useState<AuthView>("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmedPassword, setConfirmedPassword] = useState("");

  useEffect(() => {
    let active = true;

    void auth
      .restoreSession()
      .then((signedIn) => {
        if (active) {
          setView(signedIn ? "signed_in" : "signed_out");
        }
      })
      .catch(() => {
        if (active) {
          setError("Unable to check your session. Try again.");
          setView("signed_out");
        }
      });

    return () => {
      active = false;
    };
  }, [auth]);

  async function handleSignIn(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      const outcome = await auth.signIn(email.trim(), password);
      setPassword("");
      setView(outcome === "signed_in" ? "signed_in" : "new_password");
    } catch {
      setPassword("");
      setError("Sign-in failed. Check your credentials and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleNewPassword(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (newPassword !== confirmedPassword) {
      setError("The new passwords must match.");
      return;
    }

    setBusy(true);
    try {
      await auth.confirmNewPassword(newPassword);
      setNewPassword("");
      setConfirmedPassword("");
      setView("signed_in");
    } catch {
      setError("The password could not be updated. Check the requirements and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSignOut() {
    setBusy(true);
    setError(null);
    try {
      await auth.signOut();
      setView("signed_out");
    } catch {
      setError("Sign-out failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (view === "checking") {
    return (
      <section className="auth-panel" aria-labelledby="auth-heading" aria-live="polite">
        <p className="eyebrow">Private workspace</p>
        <h2 id="auth-heading">Checking your session…</h2>
      </section>
    );
  }

  if (view === "signed_in") {
    return (
      <section className="auth-panel auth-panel-workspace" aria-labelledby="auth-heading">
        <p className="eyebrow">Private workspace</p>
        <h2 id="auth-heading">You’re signed in.</h2>
        <p>Your session is limited to this browser tab.</p>
        {error === null ? null : (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button
          className="button button-secondary"
          type="button"
          disabled={busy}
          onClick={() => {
            void handleSignOut();
          }}
        >
          {busy ? "Signing out…" : "Sign out"}
        </button>
        {children}
      </section>
    );
  }

  if (view === "new_password") {
    return (
      <section className="auth-panel" aria-labelledby="auth-heading">
        <p className="eyebrow">First sign-in</p>
        <h2 id="auth-heading">Choose a permanent password.</h2>
        <form
          className="auth-form"
          aria-busy={busy}
          onSubmit={(event) => {
            void handleNewPassword(event);
          }}
        >
          <label htmlFor="new-password">New password</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            minLength={14}
            required
            value={newPassword}
            onChange={(event) => {
              setNewPassword(event.target.value);
            }}
            aria-describedby="password-requirements"
          />
          <label htmlFor="confirmed-password">Confirm new password</label>
          <input
            id="confirmed-password"
            type="password"
            autoComplete="new-password"
            minLength={14}
            required
            value={confirmedPassword}
            onChange={(event) => {
              setConfirmedPassword(event.target.value);
            }}
          />
          <p id="password-requirements" className="form-help">
            Use at least 14 characters with uppercase, lowercase, numeric, and symbol characters.
          </p>
          {error === null ? null : (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="button" type="submit" disabled={busy}>
            {busy ? "Updating password…" : "Set password"}
          </button>
        </form>
      </section>
    );
  }

  return (
    <section className="auth-panel" aria-labelledby="auth-heading">
      <p className="eyebrow">Private workspace</p>
      <h2 id="auth-heading">Sign in to Praxis.</h2>
      <form
        className="auth-form"
        aria-busy={busy}
        onSubmit={(event) => {
          void handleSignIn(event);
        }}
      >
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        {error === null ? null : (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="button" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </section>
  );
}
