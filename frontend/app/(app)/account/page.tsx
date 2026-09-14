import Link from "next/link";
import { redirect } from "next/navigation";

import { Card } from "@/components/ui";
import { getAccount, signIn, signOut, signUp } from "@/lib/auth";
import { ApiError } from "@/lib/api";

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
  const account = await getAccount();
  const params = await searchParams;
  const registering = params.mode === "register";

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
