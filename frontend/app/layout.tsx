import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

/**
 * Downloaded at build time and served from this origin - no request reaches
 * Google when somebody opens the page. That is a legal requirement here, not
 * a performance preference: a remote webfont hands the visitor's IP address to
 * a third country before they have consented to anything.
 */
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Produce Your Brand",
  description:
    "Describe what you want to customise. Produce Your Brand works out how it can be made and who can make it.",
};

/**
 * Deliberately bare. The marketing page (`/`) and the working app (the
 * `(app)` route group) each own their own header and footer - see
 * app/page.tsx and app/(app)/layout.tsx - because a prospective customer and
 * someone mid-project need different chrome. This root layout only supplies
 * what every page needs regardless: the HTML shell and global styles.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={spaceGrotesk.variable}>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
