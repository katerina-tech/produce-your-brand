/**
 * Accounts, server-side only.
 *
 * The browser never talks to the API here either, so the session cookie has to
 * be carried across the seam by hand: a read forwards the cookie it was given,
 * and a sign-in copies the cookie the API sets onto this app's own response.
 *
 * Signing in is optional throughout. `getAccount()` returning `null` is an
 * ordinary answer, not a failure - an evaluator following a link has to reach
 * the same product a signed-in user does, and a login wall would make that link
 * a dead end.
 */

import { cookies } from "next/headers";

import { ApiError } from "./api";

const BASE = process.env.API_BASE_URL ?? "http://127.0.0.1:8000/api";

export const SESSION_COOKIE = "pys_session";

export interface Account {
  id: string;
  email: string;
}

/** Who is signed in on this request, or null. Never throws. */
export async function getAccount(): Promise<Account | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;

  try {
    const response = await fetch(`${BASE}/auth/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${token}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Account | null;
    return body ?? null;
  } catch {
    // A signed-out header is a better outcome than a crashed page when the
    // API is briefly unreachable.
    return null;
  }
}

/** The cookie header to forward, so the API knows whose projects to return. */
export async function sessionHeader(): Promise<Record<string, string>> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return token ? { cookie: `${SESSION_COOKIE}=${token}` } : {};
}

async function authenticate(
  path: "login" | "register",
  email: string,
  password: string,
): Promise<Account> {
  const response = await fetch(`${BASE}/auth/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  const body = await response.json().catch(() => null);

  if (!response.ok) {
    const detail =
      (body as { error?: { message?: string }; detail?: string } | null)?.error?.message ??
      (body as { detail?: string } | null)?.detail ??
      "Sign-in failed.";
    throw new ApiError(detail, response.status);
  }

  // Copy the API's session cookie onto this app's response, so the browser
  // holds one cookie for one origin and never sees the API at all.
  const raw = response.headers.get("set-cookie");
  const value = raw?.match(new RegExp(`${SESSION_COOKIE}=([^;]+)`))?.[1];
  if (value) {
    (await cookies()).set({
      name: SESSION_COOKIE,
      value,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 60 * 60 * 24 * 14,
    });
  }

  return body as Account;
}

export const signIn = (email: string, password: string) => authenticate("login", email, password);
export const signUp = (email: string, password: string) =>
  authenticate("register", email, password);

export async function signOut(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}
