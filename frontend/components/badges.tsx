import type { ReactNode } from "react";

export function Badge({
  tone = "neutral",
  children,
  plain,
}: {
  tone?: "low" | "medium" | "high" | "critical" | "neutral" | "info";
  children: ReactNode;
  plain?: boolean;
}) {
  return <span className={`badge ${tone}${plain ? " plain" : ""}`}>{children}</span>;
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
