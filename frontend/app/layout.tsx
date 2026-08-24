import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Produce Your Stuff",
  description:
    "Describe what you want to customise. Produce Your Stuff works out how it can be made and who can make it.",
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
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
