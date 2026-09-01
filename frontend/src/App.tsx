import { AuthPanel } from "./AuthPanel";
import type { AuthClient } from "./auth";

interface AppProps {
  auth: AuthClient;
}

export function App({ auth }: AppProps) {
  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">Evidence-backed project planning</p>
        <h1>Choose what to build next.</h1>
        <p className="lede">
          Praxis connects your goals with personal evidence, then turns the strongest idea into an
          actionable project brief.
        </p>
      </header>

      <AuthPanel auth={auth} />
    </main>
  );
}
