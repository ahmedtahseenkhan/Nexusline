# Eramba — System Data Dictionary

Complete field-level reference for all **419 database tables**, organized by module.
Generated from the live database schema (`information_schema`) of this deployment.

## How to read this

- **Each table** lists every column with its data type, nullability, default, key, and what it *maps to* (foreign key or inferred `*_id` relationship).
- **Maps to** = the relationship/mapping field. `FK ->` is an enforced database foreign key; `-> (inferred)` is a relationship implied by the `*_id` column name; `polymorphic` means the link target is chosen at runtime via a companion `model` column.
- **Referenced by (FK)** lists tables that point back to this one.
- **link/join table** marks many-to-many mapping tables (e.g. `assets_risks` maps assets ↔ risks).
- **Configured values** shows the actual rows for lookup/reference tables (the selectable dropdown values in forms).

## Modules

| # | Module | Tables | Populated | File |
|--:|--------|-------:|----------:|------|
| 01 | Asset Management | 18 | 3 | [01-asset-management.md](01-asset-management.md) |
| 02 | Data Assets & Privacy (GDPR / RoPA) | 18 | 1 | [02-data-assets-privacy.md](02-data-assets-privacy.md) |
| 03 | Business Organization (Units, Processes, Legal) | 10 | 0 | [03-business-organization.md](03-business-organization.md) |
| 04 | Risk Management | 26 | 5 | [04-risk-management.md](04-risk-management.md) |
| 05 | Third-Party Risk & Vendor Assessments | 22 | 1 | [05-third-party-risk.md](05-third-party-risk.md) |
| 06 | Internal Controls (Security Services) | 17 | 3 | [06-internal-controls.md](06-internal-controls.md) |
| 07 | Policy Management | 9 | 1 | [07-policy-management.md](07-policy-management.md) |
| 08 | Compliance Management | 30 | 3 | [08-compliance-management.md](08-compliance-management.md) |
| 09 | Business Continuity Management | 22 | 1 | [09-business-continuity.md](09-business-continuity.md) |
| 10 | Security Incident Management | 8 | 1 | [10-security-incidents.md](10-security-incidents.md) |
| 11 | Exceptions Management | 10 | 0 | [11-exceptions.md](11-exceptions.md) |
| 12 | Audit Management & Account Reviews | 12 | 0 | [12-audit-account-reviews.md](12-audit-account-reviews.md) |
| 13 | Project Management | 10 | 1 | [13-projects.md](13-projects.md) |
| 14 | Awareness Programs | 21 | 0 | [14-awareness-programs.md](14-awareness-programs.md) |
| 15 | Strategy & Goals | 16 | 1 | [15-strategy-goals.md](15-strategy-goals.md) |
| 16 | Users, Roles & Access Control | 26 | 13 | [16-users-roles-access.md](16-users-roles-access.md) |
| 17 | Authentication & Directory Services | 15 | 2 | [17-authentication-directory.md](17-authentication-directory.md) |
| 18 | Custom Fields, Forms & Customization | 21 | 8 | [18-customization.md](18-customization.md) |
| 19 | Dashboards, Reports & Visualisations | 28 | 11 | [19-dashboards-reports.md](19-dashboards-reports.md) |
| 20 | Filters & Advanced Filters | 8 | 4 | [20-filters.md](20-filters.md) |
| 21 | Notifications | 12 | 1 | [21-notifications.md](21-notifications.md) |
| 22 | Workflows, Triggers, Dynamic Status & Webhooks | 24 | 5 | [22-workflows-triggers.md](22-workflows-triggers.md) |
| 23 | System Administration | 22 | 9 | [23-system-administration.md](23-system-administration.md) |
| 24 | Logs & Audit Trail | 5 | 3 | [24-logs-audit-trail.md](24-logs-audit-trail.md) |
| 25 | Shared & Cross-Cutting Objects | 9 | 2 | [25-shared-cross-cutting.md](25-shared-cross-cutting.md) |

## Conventions in this deployment

- Most user-facing records share a common envelope: `id`, `created`, `modified`, `edited`, and soft-delete via `deleted` / `deleted_date`.
- `workflow_owner_id` / `workflow_status` columns drive the approval workflow engine.
- `*_id` columns are relationships to the pluralized table of the same name (e.g. `business_unit_id` → `business_units`).
- Many-to-many relationships are stored in dedicated link tables named `<a>_<b>` (e.g. `risks_threats`).
- Lookup/reference tables (e.g. `risk_classifications`, `compliance_statuses`) hold the configurable values shown as dropdowns in forms.
