import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "NexusLine — Governance Intelligence",
  description: "NexusLine — multi-tenant Governance, Risk & Compliance platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
