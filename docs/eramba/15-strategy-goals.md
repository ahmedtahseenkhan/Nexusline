# 15. Strategy & Goals

GRC strategy: goals/objectives, goal audits & improvements, program scopes and program issues (gap/maturity items).

**Tables in this module:** 16  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `goal_audit_dates`, `goal_audit_improvements`, `goal_audit_improvements_projects`, `goal_audit_improvements_security_incidents`, `goal_audit_result_options`, `goal_audits`, `goals`, `goals_program_issues`, `goals_projects`, `goals_risks`, `goals_security_policies`, `goals_security_services`, `goals_third_party_risks`, `program_issue_types`, `program_issues`, `program_scopes`

---

### `goal_audit_dates`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `day` | int | N |  |  |  |  |
| 4 | `month` | int | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `goal_audit_improvements`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_audit_id` | int | N |  | MUL |  | FK -> `goal_audits`.id |
| 3 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `goal_audit_improvements_projects`.goal_audit_improvement_id, `goal_audit_improvements_security_incidents`.goal_audit_improvement_id

---

### `goal_audit_improvements_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_audit_improvement_id` | int | N |  | MUL |  | FK -> `goal_audit_improvements`.id |
| 3 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goal_audit_improvements_security_incidents`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_audit_improvement_id` | int | N |  | MUL |  | FK -> `goal_audit_improvements`.id |
| 3 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goal_audit_result_options`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(128) | Y |  |  |  |  |
| 3 | `hidden` | int | N | 0 |  |  |  |
| 4 | `editable` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `goal_audits`.goal_audit_result_option_id

**Configured values (2):**

| id | title | hidden | editable | created | modified |
|---|---|---|---|---|---|
| 1 | Failed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |
| 2 | Passed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |

---

### `goal_audits`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `audit_metric_description` | text | N |  |  |  |  |
| 4 | `audit_success_criteria` | text | N |  |  |  |  |
| 5 | `result` | int | Y |  |  |  |  |
| 6 | `goal_audit_result_option_id` | int | Y |  | MUL |  | FK -> `goal_audit_result_options`.id |
| 7 | `result_description` | text | N |  |  |  |  |
| 8 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 9 | `planned_date` | date | N |  |  |  |  |
| 10 | `start_date` | date | Y |  |  |  |  |
| 11 | `end_date` | date | Y |  |  |  |  |
| 12 | `workflow_owner_id` | int | Y |  |  |  |  |
| 13 | `workflow_status` | int | N | 0 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `edited` | datetime | Y |  |  |  |  |
| 17 | `deleted` | int | N | 0 |  |  |  |
| 18 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `goal_audit_improvements`.goal_audit_id

---

### `goals`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `owner_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `audit_metric_description` | text | N |  |  |  |  |
| 6 | `audit_success_criteria` | text | N |  |  |  |  |
| 7 | `status` | varchar(255) | Y |  |  |  |  |
| 8 | `audit_calendar_type` | int | N | 0 |  |  |  |
| 9 | `audit_calendar_mode` | int | N | 1 |  |  |  |
| 10 | `audit_calendar_recurrence_start_date` | date | Y |  |  |  |  |
| 11 | `audit_calendar_recurrence_frequency` | int | Y |  |  |  |  |
| 12 | `audit_calendar_recurrence_period` | int | Y |  |  |  |  |
| 13 | `workflow_owner_id` | int | Y |  |  |  |  |
| 14 | `workflow_status` | int | N | 0 |  |  |  |
| 15 | `created` | datetime | N |  |  |  |  |
| 16 | `modified` | datetime | N |  |  |  |  |
| 17 | `edited` | datetime | Y |  |  |  |  |
| 18 | `deleted` | int | N | 0 |  |  |  |
| 19 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuities_goals`.goal_id, `goal_audit_dates`.goal_id, `goal_audits`.goal_id, `goals_program_issues`.goal_id, `goals_projects`.goal_id, `goals_risks`.goal_id, `goals_security_policies`.goal_id, `goals_security_services`.goal_id, `goals_third_party_risks`.goal_id

---

### `goals_program_issues`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `program_issue_id` | int | N |  | MUL |  | FK -> `program_issues`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goals_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goals_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goals_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goals_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `goals_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `program_issue_types`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `program_issue_id` | int | N |  | MUL |  | FK -> `program_issues`.id |
| 3 | `type` | int | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `program_issues`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `issue_source` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `status` | varchar(255) | N |  |  |  |  |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |
| 10 | `edited` | datetime | Y |  |  |  |  |
| 11 | `deleted` | int | N | 0 |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `goals_program_issues`.program_issue_id, `program_issue_types`.program_issue_id

---

### `program_scopes`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `version` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `status` | varchar(255) | Y |  |  |  |  |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |
| 10 | `edited` | datetime | Y |  |  |  |  |
| 11 | `deleted` | int | N | 0 |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |

---
