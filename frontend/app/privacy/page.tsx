import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Logo } from "@/components/Logo";
import { PRIVACY_LAST_UPDATED, operator } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy — Produce Your Brand",
  description: "What this site does with your data, under GDPR Art. 13.",
};

export const dynamic = "force-dynamic";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">{title}</h2>
      <div className="mt-2 space-y-3 text-[15px] leading-relaxed text-ink-soft">{children}</div>
    </section>
  );
}

/**
 * The privacy notice (Datenschutzerklärung), under GDPR Art. 13.
 *
 * Written from what the system actually does rather than from a template, and
 * that includes the parts nobody enjoys writing: the brief somebody types is
 * sent to a model provider outside the EU, and nothing here is deleted on a
 * schedule yet. A notice that omitted those would be the kind of document that
 * exists to look compliant.
 *
 * Kept deliberately short. A page long enough that nobody finishes it is not
 * informing anyone, which is the thing Art. 13 actually asks for.
 */
export default function PrivacyPage() {
  const details = operator();

  return (
    <div className="mx-auto max-w-2xl px-5 py-12 sm:px-10 sm:py-16">
      <Link href="/" className="inline-block">
        <Logo size={22} />
      </Link>

      <h1 className="mt-10 text-2xl font-bold tracking-tight">Privacy</h1>
      <p className="mt-1.5 text-sm text-ink-muted">
        Information under Art. 13 GDPR · last updated {PRIVACY_LAST_UPDATED}
      </p>

      <Section title="Who is responsible">
        {details ? (
          <p>
            {details.name},{" "}
            <a
              href={`mailto:${details.email}`}
              className="text-accent underline underline-offset-4"
            >
              {details.email}
            </a>
            . Full details in the{" "}
            <Link href="/impressum" className="text-accent underline underline-offset-4">
              Impressum
            </Link>
            .
          </p>
        ) : (
          <p>
            This deployment has not been configured with operator details, so it
            should be treated as an unpublished prototype. See the{" "}
            <Link href="/impressum" className="text-accent underline underline-offset-4">
              Impressum
            </Link>
            .
          </p>
        )}
      </Section>

      <Section title="What happens when you use this site without an account">
        <p>
          You write a description of what you want produced. That text is sent
          to a language model to be turned into a structured brief, and is
          stored with your project so you can come back to it.
        </p>
        <p>
          If you attach a design, the file is stored on the server that runs
          this site. If you use dictation, your browser — not this site — sends
          the audio to its own speech service; this site receives only the text.
        </p>
        <p>
          <strong className="font-medium text-ink">No analytics, no tracking, no advertising.</strong>{" "}
          The only cookie this site sets is the one that keeps you signed in, and
          it is only set once you sign in. That is why there is no cookie banner:
          there is nothing to ask you about.
        </p>
      </Section>

      <Section title="If you create an account">
        <p>
          Your email address and a hash of your password are stored. The password
          itself is never stored and cannot be recovered from the hash. Your
          projects then belong to you and stop being visible to anyone else.
        </p>
        <p>
          The session cookie is technically necessary for signing in, so it rests
          on Art. 6(1)(b) GDPR — performing the service you asked for — rather
          than on consent.
        </p>
      </Section>

      <Section title="Who else sees your text">
        <p>
          <strong className="font-medium text-ink">A language model provider.</strong>{" "}
          Your project description is sent to OpenRouter, which routes it to a
          model provider. This can mean processing outside the EU, including in
          the United States. If that matters to you, do not put confidential or
          personal information into a project description.
        </p>
        <p>
          <strong className="font-medium text-ink">The hosting provider.</strong>{" "}
          This site and its database run on Railway, which necessarily processes
          what is stored on it.
        </p>
        <p>
          <strong className="font-medium text-ink">
            A tracing service, where the operator has switched it on.
          </strong>{" "}
          When configured, Langfuse records what each step of the agent received
          and returned, which includes your project text.
        </p>
        <p>
          <strong className="font-medium text-ink">OpenStreetMap, only if you open the map.</strong>{" "}
          Searches for nearby businesses are made by this site&rsquo;s server, so
          looking at the list sends nothing about you anywhere. The map is
          different: opening it makes your browser fetch tiles from
          OpenStreetMap, which means they see your IP address. It loads only
          when you ask for it, and the panel says so at that moment.
        </p>
        <p>
          Fonts are served from this site rather than from Google, so simply
          opening a page contacts nobody but us.
        </p>
      </Section>

      <Section title="What this site never does">
        <p>
          It does not contact any company for you. When you choose to write to a
          partner, the message opens in your own email, under your own address,
          and is sent by you. No supplier email addresses are stored here.
        </p>
      </Section>

      <Section title="How long things are kept">
        <p>
          Plainly: <strong className="font-medium text-ink">indefinitely</strong>.
          Projects, uploads and accounts are kept until they are deleted on
          request. There is no automatic deletion schedule yet, and this notice
          says so rather than implying one exists.
        </p>
        <p>
          Write to the address above to have a project, an upload or an account
          deleted, and it will be.
        </p>
      </Section>

      <Section title="Your rights">
        <p>
          You have the right to access, rectification, erasure, restriction, data
          portability and objection (Art. 15–21 GDPR), and the right to complain
          to a supervisory authority — in Berlin, the Berliner Beauftragte für
          Datenschutz und Informationsfreiheit.
        </p>
      </Section>

      <p className="mt-10 text-sm">
        <Link href="/impressum" className="text-accent underline underline-offset-4">
          Impressum
        </Link>
        {" · "}
        <Link href="/" className="text-accent underline underline-offset-4">
          Back to the site
        </Link>
      </p>
    </div>
  );
}
