# 22. Workflows, Triggers, Dynamic Status & Webhooks

Automation: approval/validation workflows, status triggers, dynamic (custom) statuses, and outbound webhooks.

**Tables in this module:** 24  ·  **Populated:** 5  ·  Back to [index](00-index.md)

**Table list:** `dynamic_status_conditions`, `dynamic_status_deltas`, `dynamic_status_value_logs`, `dynamic_status_values`, `dynamic_statuses`, `dynamic_statuses_report_block_chart_settings`, `status_triggers`, `trigger_logs`, `trigger_secrets`, `triggers`, `webhook_requests`, `webhooks`, `workflow_acknowledgements`, `workflow_items`, `workflow_logs`, `workflows`, `workflows_all_approver_items`, `workflows_all_validator_items`, `workflows_approver_scopes`, `workflows_approvers`, `workflows_custom_approvers`, `workflows_custom_validators`, `workflows_validator_scopes`, `workflows_validators`

---

### `dynamic_status_conditions`

*Rows: 272*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `dynamic_status_id` | int | N |  | MUL |  | FK -> `dynamic_statuses`.id |
| 3 | `type` | int | N |  |  |  |  |
| 4 | `chain_type` | int | N |  |  |  |  |
| 5 | `model` | varchar(255) | N |  |  |  |  |
| 6 | `assoc` | varchar(255) | N |  |  |  |  |
| 7 | `field` | varchar(255) | N |  |  |  |  |
| 8 | `comparison` | int | Y |  |  |  |  |
| 9 | `value` | varchar(255) | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `dynamic_status_deltas`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `dynamic_status_id` | int | N |  | MUL |  | FK -> `dynamic_statuses`.id |
| 3 | `model` | varchar(255) | N |  |  |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `value` | tinyint(1) | N |  |  |  |  |
| 6 | `migrated` | tinyint(1) | N | 0 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

---

### `dynamic_status_value_logs`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `dynamic_status_id` | int | N |  | MUL |  | FK -> `dynamic_statuses`.id |
| 3 | `model` | varchar(255) | N |  | MUL |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `value` | int | N |  |  |  |  |
| 6 | `created` | date | N |  |  |  |  |

---

### `dynamic_status_values`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `dynamic_status_id` | int | N |  | MUL |  | FK -> `dynamic_statuses`.id |
| 3 | `model` | varchar(255) | N |  | MUL |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `value` | int | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `dynamic_statuses`

*Rows: 207*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `slug` | varchar(255) | Y |  |  |  |  |
| 3 | `icon` | varchar(255) | Y |  |  |  |  |
| 4 | `name` | varchar(255) | N |  |  |  |  |
| 5 | `description` | text | Y |  |  |  |  |
| 6 | `model` | varchar(255) | N |  |  |  |  |
| 7 | `field` | varchar(255) | Y |  |  |  |  |
| 8 | `trigger` | int | N |  |  |  |  |
| 9 | `dependent` | int | N | 0 |  |  |  |
| 10 | `type` | int | N |  |  |  |  |
| 11 | `color` | varchar(255) | N |  |  |  |  |
| 12 | `status` | int | N |  |  |  |  |
| 13 | `migrated` | tinyint(1) | N | 0 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `dynamic_status_conditions`.dynamic_status_id, `dynamic_status_deltas`.dynamic_status_id, `dynamic_status_value_logs`.dynamic_status_id, `dynamic_status_values`.dynamic_status_id, `dynamic_statuses_report_block_chart_settings`.dynamic_status_id, `notification_system_items`.dynamic_status_id

**Configured values (120):**

| id | slug | icon | name | description | model | field | trigger | dependent | type | color | status | migrated | created | modified |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | missing-evidence |  | Missing Competence Evidence | Attach evidence of the competences for this role | TeamRoles |  | 1 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:37 | 2026-06-18 22:08:37 |
| 2 | disabled |  | Disabled |  | Users |  | 1 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:37 | 2026-06-18 22:08:37 |
| 3 | api-enabled |  | API Enabled |  | Users |  | 1 | 0 | 1 | #1D4FD7 | 1 | 0 | 2026-06-18 22:08:37 | 2026-06-18 22:08:37 |
| 4 | initiated |  | Incomplete |  | SecurityIncidentStagesSecurityIncidents |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:37 | 2026-06-18 22:08:37 |
| 5 | completed |  | Completed |  | SecurityIncidentStagesSecurityIncidents |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:37 | 2026-06-18 22:08:37 |
| 6 | closed |  | Closed |  | SecurityIncidents |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 7 | ongoing |  | Ongoing |  | SecurityIncidents |  | 1 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 8 | lifecycle_incomplete |  | Lifecycle Incomplete |  | SecurityIncidents |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 9 | expired |  | Expired |  | SecurityIncidents |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 10 | expired |  | Expired |  | AssetReviews |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 11 | deadline-approaching |  | Deadline Approaching |  | AssetReviews |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 12 | current |  | Current |  | AssetReviews |  | 2 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 13 | completed |  | Completed |  | AssetReviews |  | 1 | 0 | 1 | #166434 | 2 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 14 | risks-empty |  | No Risk Associated | There are no associated Asset Risks and Third Party Risk to this Asset | Assets |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 15 | AssetReview-expired |  | Expired Asset Review |  | Assets |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 16 | SecurityIncident-ongoing |  | Security Incident Ongoing |  | Assets |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 17 | expired |  | Expired |  | ProjectAchievements |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 18 | deadline-approaching |  | Expiring in the Next 14 days |  | ProjectAchievements |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 19 | completed |  | Completed |  | ProjectAchievements |  | 1 | 0 | 1 | #166434 | 2 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 20 | ongoing |  | Ongoing |  | Projects |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 21 | completed |  | Closed |  | Projects |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 22 | planned |  | Planned |  | Projects |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 23 | ProjectAchievement-expired |  | Task Expired |  | Projects |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 24 | ProjectAchievement-deadline-approaching |  | Task Deadline Approaching |  | Projects |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 25 | expired |  | Expired |  | Projects |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 26 | failed |  | Failed |  | SecurityServiceAudits |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 27 | expired |  | Expired |  | SecurityServiceAudits |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 28 | current |  | Current |  | SecurityServiceAudits |  | 2 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 29 | last_automation_failed |  | Automation Failed | The automation finished with a status different from 0. | SecurityServiceAudits |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 30 | completed |  | Completed |  | SecurityServiceAudits |  | 1 | 0 | 1 | #166434 | 2 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 31 | failed |  | Failed |  | SecurityServiceMaintenances |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 32 | expired |  | Expired |  | SecurityServiceMaintenances |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 33 | current |  | Current |  | SecurityServiceMaintenances |  | 2 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 34 | last_automation_failed |  | Automation Failed | The automation finished with a status different from 0. | SecurityServiceMaintenances |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 35 | completed |  | Completed |  | SecurityServiceMaintenances |  | 1 | 0 | 1 | #166434 | 2 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 36 | open |  | Open |  | SecurityServiceIssues |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 37 | expired |  | Expired |  | SecurityServiceIssues |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 38 | completed |  | Completed |  | SecurityServiceIssues |  | 1 | 0 | 1 | #166434 | 2 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 39 | security-policies-empty |  | Control without Policies | There are no procedures, standards or policies linked to this Internal Control. | SecurityServices |  | 1 | 0 | 1 | #1D4FD7 | 3 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 40 | audits-empty |  | Control without Audit Plan | The control has no audit plan defined. | SecurityServices |  | 1 | 0 | 1 | #1D4FD7 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 41 | doing-nothing |  | Control Doing Nothing | This control has no Risk, Data Flows or Compliance Requirements associated. | SecurityServices |  | 1 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 42 | current_audit_failed |  | Last Audit Failed |  | SecurityServices |  | 1 | 1 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 43 | current_audit_expired |  | Last Audit Expired |  | SecurityServices |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 44 | current_maintenance_failed |  | Last Maintenance Failed |  | SecurityServices |  | 1 | 1 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 45 | current_maintenance_expired |  | Last Maintenance Expired |  | SecurityServices |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 46 | design |  | Control in Design |  | SecurityServices |  | 1 | 0 | 1 | #C03F0C | 3 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 47 | SecurityServiceIssue-open |  | Control Issues |  | SecurityServices |  | 1 | 1 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 48 | SecurityIncident-ongoing |  | Incident Ongoing |  | SecurityServices |  | 1 | 1 | 1 | #C03F0C | 3 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 49 | Project-ongoing |  | Project Ongoing |  | SecurityServices |  | 1 | 1 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 50 | Project-planned |  | Project Planned |  | SecurityServices |  | 1 | 1 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 51 | Project-expired |  | Project Expired |  | SecurityServices |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 52 | ProjectAchievement-expired |  | Project Task Expired |  | SecurityServices |  | 1 | 1 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 53 | last_audit_automation_failed |  | Audit Automation Failed |  | SecurityServices |  | 1 | 1 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 54 | last_maintenance_automation_failed |  | Maintenance Automation Failed |  | SecurityServices |  | 1 | 1 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 55 | security-policies-empty |  | Missing Policy | There are no associated Policies to this Policy Exception | PolicyExceptions |  | 1 | 0 | 1 | #BA1C1C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 56 | expired |  | Expired |  | PolicyExceptions |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 57 | completed |  | Closed |  | PolicyExceptions |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 58 | open |  | Open |  | PolicyExceptions |  | 1 | 0 | 1 | #166434 | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 59 | expired |  | Expired |  | SecurityPolicyReviews |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| 60 | deadline-approaching |  | Deadline Approaching |  | SecurityPolicyReviews |  | 2 | 0 | 1 | #C03F0C | 1 | 0 | 2026-06-18 22:08:38 | 2026-06-18 22:08:38 |
| … 60 more rows … |

---

### `dynamic_statuses_report_block_chart_settings`

*Rows: 39 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_chart_setting_id` | int | N |  | MUL |  | FK -> `report_block_chart_settings`.id |
| 3 | `dynamic_status_id` | int | N |  | MUL |  | FK -> `dynamic_statuses`.id |

---

### `status_triggers`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `config_name` | varchar(155) | N |  |  |  |  |
| 5 | `column_name` | varchar(155) | N |  |  |  |  |
| 6 | `value` | varchar(155) | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

---

### `trigger_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `trigger_id` | int | Y |  | MUL |  | FK -> `triggers`.id |
| 3 | `model` | varchar(255) | Y |  | MUL |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 5 | `reference` | varchar(255) | Y |  |  |  |  |
| 6 | `response` | text | Y |  |  |  |  |
| 7 | `stdout` | text | Y |  |  |  |  |
| 8 | `stderr` | text | Y |  |  |  |  |
| 9 | `exit_code` | int | Y |  |  |  |  |
| 10 | `md5_hash` | varchar(128) | Y |  |  |  |  |
| 11 | `created` | datetime | Y |  |  |  |  |

---

### `trigger_secrets`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(128) | Y |  |  |  |  |
| 3 | `value` | text | Y |  |  |  |  |
| 4 | `created` | datetime | Y |  |  |  |  |
| 5 | `modified` | datetime | Y |  |  |  |  |

---

### `triggers`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | Y |  |  |  |  |
| 3 | `name` | varchar(255) | Y |  |  |  |  |
| 4 | `language` | tinyint | Y |  |  |  |  |
| 5 | `timeout` | int | Y |  |  |  |  |
| 6 | `composer_packages` | text | Y |  |  |  |  |
| 7 | `code` | text | Y |  |  |  |  |
| 8 | `global` | int | Y | 0 |  |  |  |
| 9 | `runtime` | int | Y | 0 |  |  |  |
| 10 | `md5_hash` | varchar(128) | Y |  |  |  |  |
| 11 | `storage_hash` | varchar(64) | Y |  |  |  |  |
| 12 | `created` | datetime | Y |  |  |  |  |
| 13 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feeds`.trigger_id, `notification_system_items`.trigger_id, `security_service_security_service_audit_triggers`.security_service_audit_trigger_id, `security_service_security_service_maintenance_triggers`.security_service_maintenance_trigger_id, `trigger_logs`.trigger_id

---

### `webhook_requests`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `webhook_id` | int | N |  | MUL |  | FK -> `webhooks`.id |
| 3 | `status` | int | N |  |  |  |  |
| 4 | `url` | text | N |  |  |  |  |
| 5 | `method` | int | N |  |  |  |  |
| 6 | `timeout` | int | N |  |  |  |  |
| 7 | `headers` | text | Y |  |  |  |  |
| 8 | `content` | text | Y |  |  |  |  |
| 9 | `response_code` | int | Y |  |  |  |  |
| 10 | `response_headers` | text | Y |  |  |  |  |
| 11 | `response_content` | text | Y |  |  |  |  |
| 12 | `execution_time` | int | Y |  |  |  |  |
| 13 | `error` | text | Y |  |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |

---

### `webhooks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `class` | varchar(255) | N |  |  |  |  |
| 3 | `model` | varchar(255) | Y |  |  |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 5 | `url` | text | Y |  |  |  |  |
| 6 | `method` | int | N |  |  |  |  |
| 7 | `headers` | text | N |  |  |  |  |
| 8 | `content` | text | N |  |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `webhook_requests`.webhook_id

---

### `workflow_acknowledgements`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `type` | varchar(255) | N |  |  |  |  |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 6 | `resolved` | int | N | 0 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `workflow_items`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `owner_id` | int | N |  |  |  |  |
| 5 | `status` | int | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `workflow_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `status` | int | N |  |  |  |  |
| 6 | `ip` | varchar(45) | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `workflows`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `notifications` | int | N | 1 |  |  |  |
| 5 | `parent_id` | int | Y |  | MUL |  | FK -> `workflows`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `workflows`.parent_id, `workflows_all_approver_items`.workflow_id, `workflows_all_validator_items`.workflow_id, `workflows_approver_scopes`.workflow_id, `workflows_approvers`.workflow_id, `workflows_validator_scopes`.workflow_id, `workflows_validators`.workflow_id

---

### `workflows_all_approver_items`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `workflows_all_validator_items`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `workflows_approver_scopes`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `custom_identifier` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `workflows_approvers`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `workflows_custom_approvers`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  |  |  | -> `workflows` *(inferred)* |
| 3 | `custom_identifier` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `workflows_custom_validators`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  |  |  | -> `workflows` *(inferred)* |
| 3 | `custom_identifier` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `workflows_validator_scopes`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `custom_identifier` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `workflows_validators`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `workflow_id` | int | N |  | MUL |  | FK -> `workflows`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---
