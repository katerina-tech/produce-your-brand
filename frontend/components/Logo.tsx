/**
 * The one place the brand mark and wordmark are drawn. Every other file that
 * needs a logo imports this - never re-declares the SVG paths or the
 * per-word colouring, so the mark can't drift between the header and the
 * marketing page.
 *
 * The static export at docs/assets/logo.svg is the same mark for contexts
 * outside the app (the README); keep the two in step.
 */

const MARK_PATH_BACK = "M0 0 L40 0 L40 35 L65 35 L65 65 L100 65 L100 100 L0 100 Z";
const MARK_PATH_ACCENT = "M40 0 L100 0 L100 65 L65 65 L65 35 L40 35 Z";

export function LogoMark({
  size = 24,
  reversed = false,
}: {
  size?: number;
  reversed?: boolean;
}) {
  const ink = reversed ? "#FAF9F7" : "var(--color-ink)";
  const accent = "var(--color-accent)";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d={MARK_PATH_BACK} fill={reversed ? accent : ink} />
      <path d={MARK_PATH_ACCENT} fill={reversed ? ink : accent} />
    </svg>
  );
}

export function Logo({
  size = 22,
  reversed = false,
  withWordmark = true,
}: {
  size?: number;
  reversed?: boolean;
  withWordmark?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size} reversed={reversed} />
      {withWordmark ? (
        <span
          className="inline-flex whitespace-nowrap text-[15px] font-bold tracking-tight"
          style={{ letterSpacing: "-0.01em" }}
        >
          <span style={{ color: reversed ? "#FAF9F7" : "var(--color-ink)" }}>
            PRODUCE&nbsp;
          </span>
          <span style={{ color: "var(--color-accent)" }}>YOUR&nbsp;</span>
          <span style={{ color: reversed ? "#FAF9F7" : "var(--color-ink)" }}>
            BRAND
          </span>
        </span>
      ) : null}
    </span>
  );
}
