import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Api } from "../api";
import { MeContext, ServicesContext } from "../context";
import type { Me, Role } from "../types";
import { RunList } from "./RunList";

function renderAs(role: Role) {
  const me: Me = { email: "u@example.com", platform_admin: false, teams: [{ id: "sales", name: "Sales", role }] };
  const api = { listRuns: vi.fn().mockResolvedValue({ items: [], next_cursor: null }) } as unknown as Api;
  const config = { apiBaseUrl: "/api", oidcIssuer: "http://issuer", oidcClientId: "dap-web" };
  render(
    <ServicesContext value={{ api, config }}>
      <MeContext value={me}>
        <MemoryRouter initialEntries={["/teams/sales/runs"]}>
          <Routes>
            <Route path="/teams/:team/runs" element={<RunList />} />
          </Routes>
        </MemoryRouter>
      </MeContext>
    </ServicesContext>,
  );
}

describe("run list", () => {
  it("hides the new run control from a viewer", async () => {
    renderAs("viewer");
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New run" })).not.toBeInTheDocument();
  });

  it("shows the new run control to an analyst", async () => {
    renderAs("analyst");
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New run" })).toHaveAttribute("href", "/teams/sales/runs/new");
  });
});
