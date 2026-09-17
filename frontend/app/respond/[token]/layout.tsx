import type { Metadata } from "next";
import type { ReactNode } from "react";

// The URL carries the respondent's personal link: keep it out of search indexes and out of
// the Referer header of anything the page links to.
export const metadata: Metadata = {
  title: "Questionnaire",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function RespondLayout({ children }: { children: ReactNode }) {
  return children;
}
