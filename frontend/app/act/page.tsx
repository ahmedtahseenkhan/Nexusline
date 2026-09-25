"use client";

/* Approve or reject from an e-mail.

   The e-mail's Approve / Reject buttons open this page with a single-use token
   (/act?token=…&decision=approve). Opening it decides nothing — mail scanners and link
   previewers follow links — it shows what is being decided and asks the person to
   confirm. Confirming posts the decision; the server checks the token (unused,
   unexpired, still yours, you may still decide) and records it exactly as the
   Approvals page would, segregation of duties included. No sign-in is needed: the
   token is the credential, and it works once. */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { IconNexus } from "@/components/icons";
import { DEFAULT_TENANT_SETTINGS, TenantSettingsContext, useFormat, type DateFormat } from "@/lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Decision = "approve" | "reject";

type ActionApproval = {
  id: string;
  reference: string;
  title: string;
  description: string;
  entity_type: string;
  entity_label: string;
  approver: string;
  requested_by_email: string;
  due_date: string | null;
  required_approvals: number;
  approvals_received: number;
  created_at: string | null;
  status: string;
};

type Preview = {
  state: "ready" | "used" | "expired" | "not_eligible" | "decided";
  message: string;
  organisation: string;
  user_name: string;
  expires_at: string | null;
  approval: ActionApproval | null;
  /** Why Approve would be refused for this person (they can still reject). */
  approve_blocked_reason?: string;
  date_format: string;
  timezone: string;
};

type Result = { state: string; decision: Decision; message: string; approval: ActionApproval };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    referrerPolicy: "no-referrer",
  });
  if (!res.ok) {
    let message = res.statusText || "Something went wrong";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* not JSON */
    }
    throw Object.assign(new Error(message), { status: res.status });
  }
  return res.json();
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="login-wrap">
      <div className="login-card" style={{ width: 520 }}>
        <div className="login-logo">
          <span className="logo"><IconNexus width={19} height={19} /></span>
          <span className="wordmark">Nexus<span style={{ color: "var(--primary-text)" }}>Line</span></span>
        </div>
        {children}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  if (children === null || children === undefined || children === "") return null;
  return (
    <div style={{ display: "flex", gap: 12, fontSize: 13.5, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
      <span className="muted" style={{ width: 120, flexShrink: 0 }}>{label}</span>
      <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{children}</span>
    </div>
  );
}

/** What is being decided; dates in the organisation's own format and timezone. */
function Details({ preview }: { preview: Preview }) {
  const { formatDate, formatDateTime } = useFormat();
  const a = preview.approval;
  if (!a) return null;
  return (
    <div style={{ margin: "14px 0 6px" }}>
      <Row label="Request">{`${a.reference} ${a.title}`.trim()}</Row>
      <Row label="About">{a.entity_label}</Row>
      <Row label="Details">{a.description}</Row>
      <Row label="Raised by">{a.requested_by_email}</Row>
      <Row label="Due">{a.due_date ? formatDate(a.due_date) : ""}</Row>
      {a.required_approvals > 1 && (
        <Row label="Approvals">{`${a.approvals_received} of ${a.required_approvals} so far`}</Row>
      )}
      <Row label="Link valid until">{preview.expires_at ? formatDateTime(preview.expires_at) : ""}</Row>
    </div>
  );
}

export default function ActPage() {
  const [token, setToken] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision>("approve");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get("token");
    const d = params.get("decision");
    if (d === "approve" || d === "reject") setDecision(d);
    if (!t) {
      setInvalid("This link is missing its token. Open the request in NexusLine instead.");
      return;
    }
    setToken(t);
    call<Preview>(`/actions/${encodeURIComponent(t)}`)
      .then((p) => {
        setPreview(p);
        if (p.approve_blocked_reason) setDecision("reject");
      })
      .catch((e: Error) => setInvalid(e.message || "This link is not valid."));
  }, []);

  const settings = useMemo(
    () => ({
      ...DEFAULT_TENANT_SETTINGS,
      ...(preview ? { date_format: preview.date_format as DateFormat, timezone: preview.timezone } : {}),
    }),
    [preview],
  );

  const openHref = preview?.approval ? `/approvals?id=${preview.approval.id}` : "/approvals";
  const needsReason = decision === "reject" && !comment.trim();

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    if (!token || needsReason) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await call<Result>(`/actions/${encodeURIComponent(token)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ decision, comment: comment.trim() }),
      });
      setResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The decision was not recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  let body: React.ReactNode;
  if (invalid) {
    body = (
      <>
        <h1>This link can&apos;t be used</h1>
        <p className="sub">{invalid}</p>
        <Link href="/approvals" className="btn" style={{ marginTop: 16, justifyContent: "center", width: "100%" }}>
          Open NexusLine
        </Link>
      </>
    );
  } else if (!preview) {
    body = <p className="sub">Checking the link…</p>;
  } else if (result) {
    body = (
      <>
        <h1>{result.decision === "approve" ? "Approved" : "Rejected"}</h1>
        <p className="sub" role="status">{result.message}</p>
        <Details preview={{ ...preview, approval: result.approval }} />
        <p className="muted" style={{ fontSize: 12.5 }}>
          Your decision is recorded in the request&apos;s history and the activity log as made by e-mail. This link
          no longer works.
        </p>
        <Link href={openHref} className="btn secondary" style={{ marginTop: 12, justifyContent: "center", width: "100%" }}>
          Open the request in NexusLine
        </Link>
      </>
    );
  } else if (preview.state !== "ready") {
    const heading =
      preview.state === "used" ? "Already used" : preview.state === "expired" ? "Link expired"
        : preview.state === "decided" ? "Already decided" : "You can't decide this request";
    body = (
      <>
        <h1>{heading}</h1>
        <p className="sub">{preview.message}</p>
        <Details preview={preview} />
        <Link href={openHref} className="btn" style={{ marginTop: 16, justifyContent: "center", width: "100%" }}>
          Open the request in NexusLine
        </Link>
      </>
    );
  } else {
    body = (
      <form onSubmit={confirm}>
        <h1>Confirm your decision</h1>
        <p className="sub">
          {preview.user_name ? `${preview.user_name}, ` : ""}
          {preview.organisation || "your organisation"} is waiting for your decision.
        </p>
        <Details preview={preview} />

        <fieldset style={{ border: "none", padding: 0, margin: "14px 0 0" }}>
          <legend className="label" style={{ marginBottom: 6 }}>Your decision</legend>
          <div className="seg" role="radiogroup" aria-label="Your decision">
            <button type="button" role="radio" aria-checked={decision === "approve"} className={decision === "approve" ? "on" : ""} onClick={() => setDecision("approve")} disabled={!!preview.approve_blocked_reason}>
              Approve
            </button>
            <button type="button" role="radio" aria-checked={decision === "reject"} className={decision === "reject" ? "on" : ""} onClick={() => setDecision("reject")}>
              Reject
            </button>
          </div>
          {preview.approve_blocked_reason && (
            <p className="sub" style={{ marginTop: 8 }}>
              You can&apos;t approve this: {preview.approve_blocked_reason} You can still reject it.
            </p>
          )}
        </fieldset>

        <label className="label" htmlFor="act-comment" style={{ marginTop: 12 }}>
          {decision === "reject" ? "Reason (required)" : "Comment (optional)"}
        </label>
        <textarea
          id="act-comment"
          className="input"
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={decision === "reject" ? "Why are you rejecting it?" : "Anything the requester should know"}
          style={{ resize: "vertical" }}
        />

        {error && <div className="error" role="alert">{error}</div>}

        <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 16 }} disabled={submitting || needsReason}>
          {submitting ? "Recording…" : `${decision === "approve" ? "Approve" : "Reject"} ${preview.approval?.reference || "request"}`}
        </button>
        <p className="hint">
          Nothing is decided until you press the button. The link is for you only and works once.
        </p>
      </form>
    );
  }

  return (
    <TenantSettingsContext.Provider
      value={{ settings, loading: false, error: null, reload: async () => {}, permissions: [] }}
    >
      <Shell>{body}</Shell>
    </TenantSettingsContext.Provider>
  );
}
