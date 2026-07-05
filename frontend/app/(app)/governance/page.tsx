"use client";

import { useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconUsers } from "@/components/icons";

// ------------------------------------------------------------------ local types
interface MeetingDecision {
  id: string;
  meeting_id: string;
  reference: string;
  description: string;
  decision_type: string;
  owner: string;
  due_date: string | null;
  status: string;
  completed_date: string | null;
  is_overdue: boolean;
  created_at: string;
}
interface Meeting {
  id: string;
  committee_id: string;
  reference: string;
  title: string;
  meeting_date: string | null;
  location: string;
  agenda: string;
  minutes: string;
  attendees: string;
  quorum_met: boolean;
  status: string;
  decision_count: number;
  created_at: string;
  decisions: MeetingDecision[];
}
interface Committee {
  id: string;
  reference: string;
  name: string;
  committee_type: string;
  charter: string;
  chairperson: string;
  secretary: string;
  members: string;
  meeting_frequency: string;
  status: string;
  workflow_status: string;
  meeting_count: number;
  created_at: string;
  meetings: Meeting[];
}
interface DecisionTrackerRow extends MeetingDecision {
  committee_id: string | null;
  committee_reference: string;
  committee_name: string;
  meeting_reference: string;
  meeting_title: string;
  meeting_date: string | null;
}
interface GovernanceSummary {
  committees_total: number;
  committees_active: number;
  meetings_total: number;
  meetings_held: number;
  meetings_scheduled: number;
  open_actions: number;
  overdue_actions: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const COMMITTEE_TYPE = opts([
  "board",
  "audit",
  "risk",
  "credit",
  "hr",
  "it_steering",
  "shariah",
  "alco",
  "compliance",
  "other",
]);
const COMMITTEE_STATUS = opts(["active", "dissolved"]);
const MEETING_FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const MEETING_STATUS = opts(["scheduled", "held", "minuted", "cancelled"]);
const DECISION_TYPE = opts(["decision", "action", "resolution"]);
const DECISION_STATUS = opts(["open", "in_progress", "done", "deferred"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

// ------------------------------------------------------------------ tones
const COMMITTEE_STATUS_TONE: Record<string, Tone> = { active: "low", dissolved: "neutral" };
const MEETING_STATUS_TONE: Record<string, Tone> = {
  scheduled: "info",
  held: "low",
  minuted: "low",
  cancelled: "neutral",
};
const DECISION_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  done: "low",
  deferred: "medium",
};
const DECISION_TYPE_TONE: Record<string, Tone> = {
  decision: "info",
  action: "medium",
  resolution: "info",
};

// ------------------------------------------------------------------ committee form state
type CommitteeForm = {
  name: string;
  committee_type: string;
  chairperson: string;
  secretary: string;
  members: string;
  meeting_frequency: string;
  status: string;
  charter: string;
  workflow_status: string;
};
const BLANK_COMMITTEE: CommitteeForm = {
  name: "",
  committee_type: "board",
  chairperson: "",
  secretary: "",
  members: "",
  meeting_frequency: "quarterly",
  status: "active",
  charter: "",
  workflow_status: "draft",
};
function fromCommittee(c: Committee): CommitteeForm {
  return {
    name: c.name,
    committee_type: c.committee_type || "board",
    chairperson: c.chairperson || "",
    secretary: c.secretary || "",
    members: c.members || "",
    meeting_frequency: c.meeting_frequency || "quarterly",
    status: c.status || "active",
    charter: c.charter || "",
    workflow_status: c.workflow_status || "draft",
  };
}
function committeePayload(f: CommitteeForm): Record<string, unknown> {
  return {
    name: f.name,
    committee_type: f.committee_type,
    chairperson: f.chairperson,
    secretary: f.secretary,
    members: f.members,
    meeting_frequency: f.meeting_frequency,
    status: f.status,
    charter: f.charter,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ meeting form state
type MeetingForm = {
  title: string;
  meeting_date: string;
  location: string;
  status: string;
  quorum_met: boolean;
  agenda: string;
  minutes: string;
  attendees: string;
};
const BLANK_MEETING: MeetingForm = {
  title: "",
  meeting_date: "",
  location: "",
  status: "scheduled",
  quorum_met: false,
  agenda: "",
  minutes: "",
  attendees: "",
};
function fromMeeting(m: Meeting): MeetingForm {
  return {
    title: m.title,
    meeting_date: m.meeting_date || "",
    location: m.location || "",
    status: m.status || "scheduled",
    quorum_met: !!m.quorum_met,
    agenda: m.agenda || "",
    minutes: m.minutes || "",
    attendees: m.attendees || "",
  };
}
function meetingPayload(f: MeetingForm): Record<string, unknown> {
  return {
    title: f.title,
    meeting_date: f.meeting_date || null,
    location: f.location,
    status: f.status,
    quorum_met: f.quorum_met,
    agenda: f.agenda,
    minutes: f.minutes,
    attendees: f.attendees,
  };
}

// inline drafts
type MeetingDraft = { title: string; meeting_date: string; location: string; status: string };
const BLANK_MEETING_DRAFT: MeetingDraft = { title: "", meeting_date: "", location: "", status: "scheduled" };

type DecisionDraft = {
  description: string;
  decision_type: string;
  owner: string;
  due_date: string;
  status: string;
};
const BLANK_DECISION_DRAFT: DecisionDraft = {
  description: "",
  decision_type: "decision",
  owner: "",
  due_date: "",
  status: "open",
};

// ------------------------------------------------------------------ sections
type SectionId = "committees" | "tracker";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "committees", label: "Committees & Meetings" },
  { id: "tracker", label: "Action Tracker" },
];

export default function GovernancePage() {
  const [section, setSection] = useState<SectionId>("committees");
  const [error, setError] = useState<string | null>(null);

  const [committees, setCommittees] = useState<Committee[]>([]);
  const [tracker, setTracker] = useState<DecisionTrackerRow[]>([]);
  const [summary, setSummary] = useState<GovernanceSummary | null>(null);
  const [trackerFilter, setTrackerFilter] = useState<string>("");
  const [trackerOverdue, setTrackerOverdue] = useState(false);

  // ---- committee dialog + expanded detail ----
  const [editingCommittee, setEditingCommittee] = useState<Committee | null>(null);
  const [showCommitteeForm, setShowCommitteeForm] = useState(false);
  const [savingCommittee, setSavingCommittee] = useState(false);
  const [cf, setCf] = useState<CommitteeForm>(BLANK_COMMITTEE);
  const setC = <K extends keyof CommitteeForm>(k: K, v: CommitteeForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  const [openCommittee, setOpenCommittee] = useState<Committee | null>(null);
  const [openMeetingId, setOpenMeetingId] = useState<string | null>(null);
  const [meetingDraft, setMeetingDraft] = useState<MeetingDraft>(BLANK_MEETING_DRAFT);
  const setMD = <K extends keyof MeetingDraft>(k: K, v: MeetingDraft[K]) => setMeetingDraft((p) => ({ ...p, [k]: v }));
  const [decisionDraft, setDecisionDraft] = useState<DecisionDraft>(BLANK_DECISION_DRAFT);
  const setDD = <K extends keyof DecisionDraft>(k: K, v: DecisionDraft[K]) => setDecisionDraft((p) => ({ ...p, [k]: v }));

  // ---- meeting dialog (full edit) ----
  const [editingMeeting, setEditingMeeting] = useState<Meeting | null>(null);
  const [showMeetingForm, setShowMeetingForm] = useState(false);
  const [savingMeeting, setSavingMeeting] = useState(false);
  const [mf, setMf] = useState<MeetingForm>(BLANK_MEETING);
  const setM = <K extends keyof MeetingForm>(k: K, v: MeetingForm[K]) => setMf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadCommittees(keepOpen?: string) {
    try {
      const res = await apiCall<Page<Committee>>("GET", "/governance?limit=200");
      setCommittees(res.items);
      if (keepOpen) setOpenCommittee(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load committees");
    }
  }
  async function refreshCommittee(id: string) {
    const c = await apiCall<Committee>("GET", `/governance/${id}`);
    setOpenCommittee(c);
    setCommittees((prev) => prev.map((x) => (x.id === id ? c : x)));
  }
  async function loadTracker() {
    try {
      const qs = new URLSearchParams();
      if (trackerFilter) qs.set("status", trackerFilter);
      if (trackerOverdue) qs.set("overdue", "true");
      const q = qs.toString();
      setTracker(await apiCall<DecisionTrackerRow[]>("GET", `/meeting-decisions${q ? `?${q}` : ""}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load action tracker");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<GovernanceSummary>("GET", "/governance-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load governance summary");
    }
  }

  useEffect(() => {
    loadCommittees();
    loadSummary();
  }, []);
  useEffect(() => {
    if (section === "tracker") loadTracker();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, trackerFilter, trackerOverdue]);

  // ------------------------------------------------------------- committee CRUD
  function openNewCommittee() {
    setEditingCommittee(null);
    setCf(BLANK_COMMITTEE);
    setShowCommitteeForm(true);
  }
  function openEditCommittee(c: Committee) {
    setEditingCommittee(c);
    setCf(fromCommittee(c));
    setShowCommitteeForm(true);
  }
  async function saveCommittee() {
    setError(null);
    setSavingCommittee(true);
    try {
      const payload = committeePayload(cf);
      if (editingCommittee) await apiCall<Committee>("PATCH", `/governance/${editingCommittee.id}`, payload);
      else await apiCall<Committee>("POST", "/governance", payload);
      setShowCommitteeForm(false);
      await loadCommittees(openCommittee?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save committee");
    } finally {
      setSavingCommittee(false);
    }
  }
  async function removeCommittee(c: Committee) {
    if (!window.confirm(`Delete committee ${c.reference || c.name}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/governance/${c.id}`);
      setShowCommitteeForm(false);
      if (openCommittee?.id === c.id) setOpenCommittee(null);
      await loadCommittees();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleCommittee(c: Committee) {
    setMeetingDraft(BLANK_MEETING_DRAFT);
    setDecisionDraft(BLANK_DECISION_DRAFT);
    setOpenMeetingId(null);
    setOpenCommittee(openCommittee?.id === c.id ? null : c);
  }

  // ------------------------------------------------------------- meeting CRUD (inline add + modal edit)
  async function addMeeting() {
    if (!openCommittee) return;
    setError(null);
    try {
      await apiCall<Committee>("POST", `/governance/${openCommittee.id}/meetings`, {
        title: meetingDraft.title,
        meeting_date: meetingDraft.meeting_date || null,
        location: meetingDraft.location,
        status: meetingDraft.status,
      });
      setMeetingDraft(BLANK_MEETING_DRAFT);
      await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to schedule meeting");
    }
  }
  function openEditMeeting(m: Meeting) {
    setEditingMeeting(m);
    setMf(fromMeeting(m));
    setShowMeetingForm(true);
  }
  async function saveMeeting() {
    if (!editingMeeting) return;
    setError(null);
    setSavingMeeting(true);
    try {
      await apiCall<Meeting>("PATCH", `/governance-meetings/${editingMeeting.id}`, meetingPayload(mf));
      setShowMeetingForm(false);
      if (openCommittee) await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save meeting");
    } finally {
      setSavingMeeting(false);
    }
  }
  async function removeMeeting(m: Meeting) {
    if (!window.confirm(`Delete meeting ${m.reference || m.title}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/governance-meetings/${m.id}`);
      if (openMeetingId === m.id) setOpenMeetingId(null);
      if (openCommittee) await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete meeting");
    }
  }
  function toggleMeeting(m: Meeting) {
    setDecisionDraft(BLANK_DECISION_DRAFT);
    setOpenMeetingId(openMeetingId === m.id ? null : m.id);
  }

  // ------------------------------------------------------------- decision CRUD (inline)
  async function addDecision(meetingId: string) {
    setError(null);
    try {
      await apiCall<Meeting>("POST", `/governance-meetings/${meetingId}/decisions`, {
        description: decisionDraft.description,
        decision_type: decisionDraft.decision_type,
        owner: decisionDraft.owner,
        due_date: decisionDraft.due_date || null,
        status: decisionDraft.status,
      });
      setDecisionDraft(BLANK_DECISION_DRAFT);
      if (openCommittee) await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add decision / action");
    }
  }
  async function setDecisionStatus(d: MeetingDecision, statusValue: string, fromTracker = false) {
    setError(null);
    try {
      await apiCall<MeetingDecision>("PATCH", `/meeting-decisions/${d.id}`, { status: statusValue });
      if (fromTracker) await loadTracker();
      else if (openCommittee) await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update decision");
    }
  }
  async function removeDecision(d: MeetingDecision, fromTracker = false) {
    if (!window.confirm(`Remove ${d.reference || "this item"}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/meeting-decisions/${d.id}`);
      if (fromTracker) await loadTracker();
      else if (openCommittee) await refreshCommittee(openCommittee.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove item");
    }
  }

  // ------------------------------------------------------------- committee form tabs
  const committeeGeneral = (
    <>
      <Field label="Name" required help="For example: Board Risk Management Committee (BRMC).">
        <TextInput value={cf.name} onChange={(v) => setC("name", v)} placeholder="Committee name" required />
      </Field>
      <div className="field-row">
        <Field label="Committee type" help="Board or management committee category.">
          <Select value={cf.committee_type} onChange={(v) => setC("committee_type", v)} options={COMMITTEE_TYPE} />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={COMMITTEE_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Chairperson">
          <TextInput value={cf.chairperson} onChange={(v) => setC("chairperson", v)} placeholder="Name" />
        </Field>
        <Field label="Secretary">
          <TextInput value={cf.secretary} onChange={(v) => setC("secretary", v)} placeholder="Name" />
        </Field>
      </div>
      <Field label="Meeting frequency" help="Mandated cadence, e.g. quarterly for most board committees.">
        <Select value={cf.meeting_frequency} onChange={(v) => setC("meeting_frequency", v)} options={MEETING_FREQ} />
      </Field>
      <Field label="Members" help="Committee membership — one per line or comma-separated.">
        <TextArea value={cf.members} onChange={(v) => setC("members", v)} rows={3} placeholder="Members and their roles." />
      </Field>
    </>
  );
  const committeeCharter = (
    <>
      <Field label="Charter" help="Terms of reference — mandate, authority and responsibilities.">
        <TextArea value={cf.charter} onChange={(v) => setC("charter", v)} rows={8} placeholder="Committee charter / terms of reference." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this committee record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- meeting form tabs
  const meetingGeneral = (
    <>
      <Field label="Title" required help="For example: Q1 2026 quarterly sitting.">
        <TextInput value={mf.title} onChange={(v) => setM("title", v)} placeholder="Meeting title" required />
      </Field>
      <div className="field-row">
        <Field label="Meeting date">
          <TextInput type="date" value={mf.meeting_date} onChange={(v) => setM("meeting_date", v)} />
        </Field>
        <Field label="Status">
          <Select value={mf.status} onChange={(v) => setM("status", v)} options={MEETING_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Location">
          <TextInput value={mf.location} onChange={(v) => setM("location", v)} placeholder="Boardroom / video" />
        </Field>
        <Field label="Quorum met">
          <Toggle checked={mf.quorum_met} onChange={(v) => setM("quorum_met", v)} label="Quorum was met" />
        </Field>
      </div>
    </>
  );
  const meetingMinutes = (
    <>
      <Field label="Agenda">
        <TextArea value={mf.agenda} onChange={(v) => setM("agenda", v)} rows={5} placeholder="Agenda items." />
      </Field>
      <Field label="Minutes">
        <TextArea value={mf.minutes} onChange={(v) => setM("minutes", v)} rows={6} placeholder="Minutes of the meeting." />
      </Field>
      <Field label="Attendees" help="Members present and apologies.">
        <TextArea value={mf.attendees} onChange={(v) => setM("attendees", v)} rows={3} placeholder="Attendance record." />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Board &amp; Committee Governance</h1>
          <p>Committee register with charters and cadence, meeting minutes with agenda &amp; attendance, and an enterprise decision / action tracker.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "committees" && (
            <button className="btn" onClick={openNewCommittee}>
              <IconPlus width={16} height={16} /> New committee
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.committees_active.toLocaleString() : "—"}</span></div>
          <span className="l">Active committees</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.meetings_scheduled.toLocaleString() : "—"}</span></div>
          <span className="l">Upcoming meetings</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.open_actions.toLocaleString() : "—"}</span></div>
          <span className="l">Open actions</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.overdue_actions.toLocaleString() : "—"}</span></div>
          <span className="l">Overdue actions</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`btn${section === s.id ? "" : " secondary"}`}
            onClick={() => setSection(s.id)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= COMMITTEES & MEETINGS */}
      {section === "committees" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Committees</h3>
              <span className="sub">{committees.length} total · click a row to manage meetings</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Chairperson</th>
                    <th>Frequency</th>
                    <th>Meetings</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {committees.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => toggleCommittee(c)}>
                      <td className="ref">{c.reference || "—"}</td>
                      <td className="cell-title">{c.name}</td>
                      <td><Badge tone="info">{cap(c.committee_type)}</Badge></td>
                      <td className="muted">{c.chairperson || "—"}</td>
                      <td className="muted">{cap(c.meeting_frequency)}</td>
                      <td className="muted">{c.meeting_count}</td>
                      <td><Badge tone={COMMITTEE_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleCommittee(c)}>
                            {openCommittee?.id === c.id ? "Hide" : "Manage"}
                          </button>
                          <button className="btn secondary sm" onClick={() => openEditCommittee(c)}>Edit</button>
                          <button className="btn secondary sm" onClick={() => removeCommittee(c)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {committees.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconUsers width={24} height={24} /></span>
                          <h3>No committees</h3>
                          <p>Constitute board and management committees with their charters, membership and meeting cadence.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openCommittee && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openCommittee.reference} — {openCommittee.name}</h3>
                    <span className="sub">
                      {cap(openCommittee.committee_type)} · {cap(openCommittee.status)}
                      {openCommittee.chairperson ? " · chair " + openCommittee.chairperson : ""}
                      {openCommittee.secretary ? " · secretary " + openCommittee.secretary : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="btn secondary sm" onClick={() => openEditCommittee(openCommittee)}>Edit</button>
                    <button className="btn secondary sm" onClick={() => removeCommittee(openCommittee)}>Delete</button>
                  </div>
                </div>

                <div className="card-pad">
                  <strong>Meetings</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Schedule a sitting, then expand it to record agenda, minutes and its decisions / actions.
                  </p>
                  <form
                    style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                    onSubmit={(ev) => { ev.preventDefault(); addMeeting(); }}
                  >
                    <div style={{ flex: "1 1 220px" }}>
                      <label className="label">Title</label>
                      <input className="input" value={meetingDraft.title} onChange={(ev) => setMD("title", ev.target.value)} placeholder="Meeting title" required />
                    </div>
                    <div style={{ width: 160 }}>
                      <label className="label">Date</label>
                      <input className="input" type="date" value={meetingDraft.meeting_date} onChange={(ev) => setMD("meeting_date", ev.target.value)} />
                    </div>
                    <div style={{ width: 180 }}>
                      <label className="label">Location</label>
                      <input className="input" value={meetingDraft.location} onChange={(ev) => setMD("location", ev.target.value)} placeholder="Boardroom / video" />
                    </div>
                    <div style={{ width: 150 }}>
                      <label className="label">Status</label>
                      <select className="select" value={meetingDraft.status} onChange={(ev) => setMD("status", ev.target.value)}>
                        {MEETING_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                      </select>
                    </div>
                    <button className="btn">Add</button>
                  </form>

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Ref</th>
                          <th>Title</th>
                          <th>Date</th>
                          <th>Location</th>
                          <th>Quorum</th>
                          <th>Items</th>
                          <th>Status</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {openCommittee.meetings.map((m) => (
                          <MeetingRows
                            key={m.id}
                            meeting={m}
                            open={openMeetingId === m.id}
                            onToggle={() => toggleMeeting(m)}
                            onEdit={() => openEditMeeting(m)}
                            onDelete={() => removeMeeting(m)}
                            decisionDraft={decisionDraft}
                            setDD={setDD}
                            onAddDecision={() => addDecision(m.id)}
                            onDecisionStatus={(d, s) => setDecisionStatus(d, s)}
                            onRemoveDecision={(d) => removeDecision(d)}
                          />
                        ))}
                        {openCommittee.meetings.length === 0 && (
                          <tr><td colSpan={8}><span className="muted">No meetings recorded yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <RecordPanels model="committee" entityId={openCommittee.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= ACTION TRACKER */}
      {section === "tracker" && (
        <div className="card">
          <div className="card-head row-between">
            <div>
              <h3>Decision &amp; Action Tracker</h3>
              <span className="sub">{tracker.length} items across all committees</span>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select className="select" style={{ width: 170 }} value={trackerFilter} onChange={(e) => setTrackerFilter(e.target.value)}>
                <option value="">All statuses</option>
                {DECISION_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
              </select>
              <label className="switch" style={{ whiteSpace: "nowrap" }}>
                <input type="checkbox" checked={trackerOverdue} onChange={(e) => setTrackerOverdue(e.target.checked)} />
                <span className="track" />
                <span className="txt">Overdue only</span>
              </label>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Description</th>
                  <th>Type</th>
                  <th>Committee</th>
                  <th>Meeting</th>
                  <th>Owner</th>
                  <th>Due</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {tracker.map((d) => (
                  <tr key={d.id} style={d.is_overdue ? { background: "var(--danger-bg, rgba(192,57,43,0.06))" } : undefined}>
                    <td className="ref">{d.reference || "—"}</td>
                    <td className="cell-title">{d.description}</td>
                    <td><Badge tone={DECISION_TYPE_TONE[d.decision_type] || "neutral"}>{cap(d.decision_type)}</Badge></td>
                    <td className="muted">{d.committee_name || "—"}</td>
                    <td className="muted">{d.meeting_title || "—"}</td>
                    <td className="muted">{d.owner || "—"}</td>
                    <td>
                      {d.is_overdue ? (
                        <Badge tone="critical">Overdue · {d.due_date}</Badge>
                      ) : (
                        <span className="muted">{d.due_date || "—"}</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <select
                        className="select"
                        style={{ minWidth: 130 }}
                        value={d.status}
                        onChange={(e) => setDecisionStatus(d, e.target.value, true)}
                      >
                        {DECISION_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                      </select>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeDecision(d, true)}>Remove</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {tracker.length === 0 && (
                  <tr>
                    <td colSpan={9}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No decisions or actions</h3>
                        <p>Log decisions, actions and resolutions against committee meetings — they roll up here for enterprise-wide follow-up.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= MODALS */}
      {showCommitteeForm && (
        <FormModal
          title={editingCommittee ? `Edit committee — ${editingCommittee.reference || editingCommittee.name}` : "New committee"}
          wide
          tabs={[
            { id: "general", label: "General", content: committeeGeneral, required: true },
            { id: "charter", label: "Charter", content: committeeCharter },
          ]}
          onClose={() => setShowCommitteeForm(false)}
          onSave={saveCommittee}
          saving={savingCommittee}
          error={error}
          saveLabel={editingCommittee ? "Save changes" : "Create committee"}
          footerLeft={
            editingCommittee ? (
              <button className="btn secondary sm" type="button" onClick={() => removeCommittee(editingCommittee)} disabled={savingCommittee} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showMeetingForm && editingMeeting && (
        <FormModal
          title={`Edit meeting — ${editingMeeting.reference || editingMeeting.title}`}
          wide
          tabs={[
            { id: "general", label: "General", content: meetingGeneral, required: true },
            { id: "minutes", label: "Agenda & Minutes", content: meetingMinutes },
          ]}
          onClose={() => setShowMeetingForm(false)}
          onSave={saveMeeting}
          saving={savingMeeting}
          error={error}
          saveLabel="Save changes"
          footerLeft={
            <button className="btn secondary sm" type="button" onClick={() => removeMeeting(editingMeeting)} disabled={savingMeeting} style={{ color: "var(--danger, #c0392b)" }}>
              Delete
            </button>
          }
        />
      )}
    </>
  );
}

// ------------------------------------------------------------------ meeting row + expanded decisions
function MeetingRows({
  meeting,
  open,
  onToggle,
  onEdit,
  onDelete,
  decisionDraft,
  setDD,
  onAddDecision,
  onDecisionStatus,
  onRemoveDecision,
}: {
  meeting: Meeting;
  open: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  decisionDraft: DecisionDraft;
  setDD: <K extends keyof DecisionDraft>(k: K, v: DecisionDraft[K]) => void;
  onAddDecision: () => void;
  onDecisionStatus: (d: MeetingDecision, status: string) => void;
  onRemoveDecision: (d: MeetingDecision) => void;
}) {
  return (
    <>
      <tr style={{ cursor: "pointer" }} onClick={onToggle}>
        <td className="ref">{meeting.reference || "—"}</td>
        <td className="cell-title">{meeting.title}</td>
        <td className="muted">{meeting.meeting_date || "—"}</td>
        <td className="muted">{meeting.location || "—"}</td>
        <td>{meeting.quorum_met ? <Badge tone="low">Met</Badge> : <span className="muted">—</span>}</td>
        <td className="muted">{meeting.decision_count}</td>
        <td><Badge tone={MEETING_STATUS_TONE[meeting.status] || "neutral"}>{cap(meeting.status)}</Badge></td>
        <td>
          <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
            <button className="btn secondary sm" onClick={onToggle}>{open ? "Hide" : "Open"}</button>
            <button className="btn secondary sm" onClick={onEdit}>Edit</button>
            <button className="btn secondary sm" onClick={onDelete}>Delete</button>
          </div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={8} style={{ background: "var(--surface-2, rgba(0,0,0,0.02))" }}>
            <div style={{ padding: "4px 4px 8px" }}>
              {(meeting.agenda || meeting.minutes || meeting.attendees) && (
                <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
                  {meeting.agenda && (
                    <div>
                      <div className="label">Agenda</div>
                      <div className="muted" style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{meeting.agenda}</div>
                    </div>
                  )}
                  {meeting.minutes && (
                    <div>
                      <div className="label">Minutes</div>
                      <div className="muted" style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{meeting.minutes}</div>
                    </div>
                  )}
                  {meeting.attendees && (
                    <div>
                      <div className="label">Attendees</div>
                      <div className="muted" style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{meeting.attendees}</div>
                    </div>
                  )}
                </div>
              )}

              <strong style={{ fontSize: 13 }}>Decisions &amp; actions</strong>
              <form
                style={{ display: "flex", gap: 8, margin: "10px 0 12px", alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); onAddDecision(); }}
              >
                <div style={{ flex: "1 1 240px" }}>
                  <label className="label">Description</label>
                  <input className="input" value={decisionDraft.description} onChange={(ev) => setDD("description", ev.target.value)} placeholder="Decision / action / resolution" required />
                </div>
                <div style={{ width: 140 }}>
                  <label className="label">Type</label>
                  <select className="select" value={decisionDraft.decision_type} onChange={(ev) => setDD("decision_type", ev.target.value)}>
                    {DECISION_TYPE.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                  </select>
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Owner</label>
                  <input className="input" value={decisionDraft.owner} onChange={(ev) => setDD("owner", ev.target.value)} placeholder="Owner" />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Due date</label>
                  <input className="input" type="date" value={decisionDraft.due_date} onChange={(ev) => setDD("due_date", ev.target.value)} />
                </div>
                <div style={{ width: 140 }}>
                  <label className="label">Status</label>
                  <select className="select" value={decisionDraft.status} onChange={(ev) => setDD("status", ev.target.value)}>
                    {DECISION_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                  </select>
                </div>
                <button className="btn">Add</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Ref</th>
                      <th>Description</th>
                      <th>Type</th>
                      <th>Owner</th>
                      <th>Due</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {meeting.decisions.map((d) => (
                      <tr key={d.id} style={d.is_overdue ? { background: "var(--danger-bg, rgba(192,57,43,0.06))" } : undefined}>
                        <td className="ref">{d.reference || "—"}</td>
                        <td className="cell-title">{d.description}</td>
                        <td><Badge tone={DECISION_TYPE_TONE[d.decision_type] || "neutral"}>{cap(d.decision_type)}</Badge></td>
                        <td className="muted">{d.owner || "—"}</td>
                        <td>
                          {d.is_overdue ? (
                            <Badge tone="critical">Overdue · {d.due_date}</Badge>
                          ) : (
                            <span className="muted">{d.due_date || "—"}</span>
                          )}
                        </td>
                        <td>
                          <select className="select" style={{ minWidth: 130 }} value={d.status} onChange={(ev) => onDecisionStatus(d, ev.target.value)}>
                            {DECISION_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                          </select>
                        </td>
                        <td>
                          <button className="btn secondary sm" onClick={() => onRemoveDecision(d)}>Remove</button>
                        </td>
                      </tr>
                    ))}
                    {meeting.decisions.length === 0 && (
                      <tr><td colSpan={7}><span className="muted">No decisions or actions recorded yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
