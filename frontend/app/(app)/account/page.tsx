import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, Notice } from "@/components/ui";
import { getAccount, signIn, signOut, signUp } from "@/lib/auth";
import { ApiError, getHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * The account screen: sign in, register, or see who you are.
 *
 * Deliberately not a gate. Nothing else in this product requires an account -
 * a visitor following a link gets the whole thing - so this page exists to let
 * somebody claim their work, not to stand in front of it.
 */
export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; mode?: string }>;
}) {
  const [account, health] = await Promise.all([getAccount(), getHealth()]);
  const params = await searchParams;
  const registering = params.mode === "register";

  // A deployment with no session secret cannot issue sessions. Everything else
  // works, so the honest move is to say so here rather than to offer a form
  // that can only fail - and to say it in terms of the thing to fix.
  // Strictly `=== false`, not falsy: a backend deployed before this field
  // existed reports nothing, and reading that absence as "switched off"
  // would announce a broken feature that works fine.
  const signInUnavailable = health?.checks.sign_in_configured === false;

  async function authenticate(formData: FormData) {
    "use server";
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");
    const mode = String(formData.get("mode") ?? "login");

    try {
      if (mode === "register") {
        await signUp(email, password);
      } else {
        await signIn(email, password);
      }
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Try again.";
      redirect(`/account?mode=${mode}&error=${encodeURIComponent(message)}`);
    }

    redirect("/dashboard");
  }

  async function endSession() {
    "use server";
    await signOut();
    redirect("/account");
  }

  if (account) {
    return (
      <div className="mx-auto max-w-lg">
        <p className="eyebrow mb-2">Account</p>
        <h1 className="mb-6 text-2xl font-bold tracking-tight">You are signed in</h1>

        <Card>
          <div className="px-5 py-5 sm:px-6">
            <p className="text-sm text-ink-muted">Signed in as</p>
            <p className="mt-1 text-[17px] font-semibold">{account.email}</p>

            <p className="mt-5 text-sm leading-relaxed text-ink-soft">
              Projects you start while signed in belong to you and appear under{" "}
              <Link href="/dashboard" className="text-accent underline underline-offset-4">
                My projects
              </Link>
              . Anything you created before signing in stays where it was.
            </p>

            <form action={endSession} className="mt-6">
              <button
                type="submit"
                className="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:border-ink-muted hover:text-ink"
              >
                Sign out
              </button>
            </form>
          </div>
        </Card>
      </div>
    );
  }

  if (signInUnavailable) {
    return (
      <div className="mx-auto max-w-lg">
        <p className="eyebrow mb-2">Account</p>
        <h1 className="mb-6 text-2xl font-bold tracking-tight">Sign-in is switched off here</h1>
        <Notice tone="warning" title="This deployment has no session secret">
          <p>
            Accounts need <code className="font-mono text-xs">PYS_SESSION_SECRET</code>{" "}
            set on the backend service. Without it nothing can be signed, so
            nobody can sign in.
          </p>
          <p className="mt-3">
            Everything else works exactly as it does with accounts switched on:
            projects, the workflow and every link keep working, and a project
            simply belongs to nobody.
          </p>
        </Notice>
        <p className="mt-4">
          <Link href="/dashboard" className="text-accent underline underline-offset-4">
            Back to projects
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg">
      <p className="eyebrow mb-2">Account</p>
      <h1 className="mb-2 text-2xl font-bold tracking-tight">
        {registering ? "Create an account" : "Sign in"}
      </h1>
      <p className="mb-6 text-[15px] leading-relaxed text-ink-soft">
        Optional. Everything works without one &mdash; an account simply keeps your
        projects together and private to you.
      </p>

      <Card>
        <form action={authenticate} className="space-y-4 px-5 py-5 sm:px-6">
          <input type="hidden" name="mode" value={registering ? "register" : "login"} />

          {params.error ? (
            <p className="rounded-lg border border-blocked/30 bg-blocked/5 px-3.5 py-2.5 text-sm text-blocked">
              {params.error}
            </p>
          ) : null}

          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
              placeholder="you@company.de"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              minLength={registering ? 10 : undefined}
              autoComplete={registering ? "new-password" : "current-password"}
              className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
              placeholder={registering ? "At least 10 characters" : ""}
            />
            {registering ? (
              <p className="mt-1.5 text-xs text-ink-muted">
                Length matters more than symbols. A short phrase you will remember beats
                a short password you will not.
              </p>
            ) : null}
          </div>

          <button
            type="submit"
            className="w-full rounded-lg bg-ink px-4 py-2.5 text-[15px] font-medium text-white transition-colors hover:bg-ink/90"
          >
            {registering ? "Create account" : "Sign in"}
          </button>

          <p className="pt-1 text-center text-sm text-ink-muted">
            {registering ? (
              <>
                Already have one?{" "}
                <Link href="/account" className="text-accent underline underline-offset-4">
                  Sign in
                </Link>
              </>
            ) : (
              <>
                No account yet?{" "}
                <Link
                  href="/account?mode=register"
                  className="text-accent underline underline-offset-4"
                >
                  Create one
                </Link>
              </>
            )}
          </p>
        </form>
      </Card>
    </div>
  );
}
