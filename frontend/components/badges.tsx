import type { ReactNode } from "react";

export type BadgeTone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

/** A status pill. `asIs` keeps the text's own casing (`.badge` capitalises every word
 *  by default, which turns "In review" into "In Review"); `hollow` draws the outline-only
 *  variant for "Not assessed" / "Not recorded" / "Never attested", so a missing judgement
 *  never looks like a real status. Both default off, so existing badges are unchanged. */
export function Badge({
  tone = "neutral",
  children,
  plain,
  asIs,
  hollow,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  plain?: boolean;
  asIs?: boolean;
  hollow?: boolean;
}) {
  return (
    <span className={`badge ${hollow ? "hollow" : tone}${plain ? " plain" : ""}${asIs ? " as-is" : ""}`}>
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

export function Severity({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={SEVERITY_TONE[value] || "neutral"}>{value}</Badge>;
}

const COMPLIANCE_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral"> = {
  compliant: "low",
  partially_compliant: "medium",
  non_compliant: "critical",
  not_assessed: "neutral",
  not_applicable: "neutral",
};

export function ComplianceBadge({ value }: { value: string }) {
  return <Badge tone={COMPLIANCE_TONE[value] || "neutral"}>{value.replace(/_/g, " ")}</Badge>;
}

const EFFECTIVENESS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral"> = {
  effective: "low",
  partially_effective: "medium",
  ineffective: "critical",
  not_assessed: "neutral",
};

export function EffectivenessBadge({ value }: { value: string }) {
  return <Badge tone={EFFECTIVENESS_TONE[value] || "neutral"}>{value.replace(/_/g, " ")}</Badge>;
}

export function StatusBadge({ value, tone = "info" }: { value: string; tone?: "info" | "neutral" }) {
  return <Badge tone={tone}>{value.replace(/_/g, " ")}</Badge>;
}
