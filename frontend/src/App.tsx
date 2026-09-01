import { AuthPanel } from "./AuthPanel";
import { GoalEntry } from "./GoalEntry";
import type { ApiClient } from "./api";
import type { AuthClient } from "./auth";

interface AppProps {
  api: ApiClient;
  auth: AuthClient;
}

export function App({ api, auth }: AppProps) {
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

      <AuthPanel auth={auth}>
        <GoalEntry api={api} />
      </AuthPanel>
    </main>
  );
}
