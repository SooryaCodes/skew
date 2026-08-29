/**
 * Operator session. No accounts, no login wall.
 *
 * The dashboard reads ?op=<token> from the URL once, keeps it IN MEMORY for
 * the tab's lifetime, and immediately strips it from the address bar so it
 * cannot leak into a screenshot, a screen share, or browser history. Without
 * the token the UI is identical but read-only — controls are not disabled,
 * they are simply never rendered.
 *
 * Deliberately not localStorage: an operator session should end when the tab
 * does, and a judge borrowing the demo URL should never inherit control.
 */

import { API_BASE } from "./api";

let token: string | null = null;

export function captureOperatorToken(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  const provided = url.searchParams.get("op");
  if (provided) {
    token = provided;
    url.searchParams.delete("op");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
  }
}

export function isOperator(): boolean {
  return token !== null;
}

export class ActionError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ActionError";
  }
}

/** POST to an action endpoint with the operator token. */
export async function operatorPost(pathAndQuery: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}${pathAndQuery}`, {
    method: "POST",
    headers: { "x-operator-token": token ?? "", accept: "application/json" },
  });
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    const detail =
      typeof body.detail === "string" ? body.detail : `${pathAndQuery} returned ${response.status}`;
    throw new ActionError(detail, response.status);
  }
  return body;
}
