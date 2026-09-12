import type { Metadata } from "next";
import type { ReactNode } from "react";

// The confirmation page's URL carries a single-use token: keep it out of search indexes
// and out of the Referer header of anything the page links to.
export const metadata: Metadata = {
  title: "Confirm your decision — NexusLine",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function ActLayout({ children }: { children: ReactNode }) {
  return children;
}
