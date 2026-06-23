import type { ReactNode } from "react";
import { IconCheck } from "./icons";

export default function ModulePlaceholder({
  title,
  description,
  icon,
  planned,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  planned: string[];
}) {
  return (
    <>
      <div className="page-head">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="card card-pad">
        <div className="empty" style={{ paddingBottom: 24 }}>
          <span className="ico">{icon}</span>
          <h3>Module on the roadmap</h3>
          <p>
            This module is scaffolded in the navigation and will follow the same
            architecture as Risk and Compliance.
          </p>
        </div>
        <div style={{ maxWidth: 560, margin: "0 auto" }}>
          {planned.map((p) => (
            <div
              key={p}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0" }}
            >
              <span
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 6,
                  background: "var(--primary-weak)",
                  color: "var(--primary)",
                  display: "grid",
                  placeItems: "center",
                  flexShrink: 0,
                }}
              >
                <IconCheck width={14} height={14} />
              </span>
              <span style={{ fontSize: 13.5 }}>{p}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
