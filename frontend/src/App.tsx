export function App() {
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

      <section className="status" aria-labelledby="status-heading">
        <div>
          <p className="status-label">Current milestone</p>
          <h2 id="status-heading">Local walking skeleton</h2>
        </div>
        <span className="status-badge">Ready</span>
      </section>
    </main>
  );
}
