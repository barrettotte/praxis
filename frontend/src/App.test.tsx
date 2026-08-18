import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("introduces the Praxis workflow", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Choose what to build next." }),
    ).toBeVisible();
    expect(screen.getByText(/personal evidence/i)).toBeVisible();
  });
});
