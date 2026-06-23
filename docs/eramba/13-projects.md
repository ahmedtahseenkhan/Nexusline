# 13. Project Management

Projects used to track remediation/improvement work: project records, statuses, expenses, achievements and links to risks/controls/policies.

**Tables in this module:** 10  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `project_achievements`, `project_expenses`, `project_overtime_graphs`, `project_statuses`, `projects`, `projects_risks`, `projects_security_policies`, `projects_security_service_audit_improvements`, `projects_security_services`, `projects_third_party_risks`

---

### `project_achievements`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `description` | text | N |  |  |  |  |
| 3 | `date` | date | N |  |  |  |  |
| 4 | `expired` | int | N | 0 |  |  |  |
| 5 | `completion` | int | N |  |  |  |  |
| 6 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 7 | `task_order` | int | N | 1 |  |  |  |
| 8 | `workflow_owner_id` | int | Y |  |  |  |  |
| 9 | `workflow_status` | int | N | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `edited` | datetime | Y |  |  |  |  |
| 13 | `deleted` | int | N | 0 |  |  |  |
| 14 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `project_expenses`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `amount` | float | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `date` | date | N |  |  |  |  |
| 5 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |
| 10 | `edited` | datetime | Y |  |  |  |  |
| 11 | `deleted` | int | N | 0 |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `project_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 3 | `current_budget` | int | N |  |  |  |  |
| 4 | `budget` | int | N |  |  |  |  |
| 5 | `timestamp` | varchar(45) | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `project_statuses`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `projects`.project_status_id

**Configured values (3):**

| id | name |
|---|---|
| 1 | Planned |
| 2 | Ongoing |
| 3 | Completed |

---

### `projects`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `goal` | text | N |  |  |  |  |
| 4 | `start` | date | N |  |  |  |  |
| 5 | `deadline` | date | N |  |  |  |  |
| 6 | `plan_budget` | int | Y |  |  |  |  |
| 7 | `project_status_id` | int | Y |  | MUL |  | FK -> `project_statuses`.id |
| 8 | `over_budget` | int | N | 0 |  |  |  |
| 9 | `expired_tasks` | int | N | 0 |  |  |  |
| 10 | `expired` | int | N | 0 |  |  |  |
| 11 | `workflow_owner_id` | int | Y |  |  |  |  |
| 12 | `workflow_status` | int | N | 0 |  |  |  |
| 13 | `created` | datetime | N |  |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |
| 15 | `edited` | datetime | Y |  |  |  |  |
| 16 | `deleted` | int | N | 0 |  |  |  |
| 17 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuities_projects`.project_id, `business_continuity_plan_audit_improvements_projects`.project_id, `compliance_managements_projects`.project_id, `data_assets_projects`.project_id, `goal_audit_improvements_projects`.project_id, `goals_projects`.project_id, `project_achievements`.project_id, `project_expenses`.project_id, `project_overtime_graphs`.project_id, `projects_risks`.project_id, `projects_security_policies`.project_id, `projects_security_service_audit_improvements`.project_id, `projects_security_services`.project_id, `projects_third_party_risks`.project_id

---

### `projects_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `risk_id` | int | Y |  | MUL |  | FK -> `risks`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `projects_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `security_policy_id` | int | Y |  | MUL |  | FK -> `security_policies`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `projects_security_service_audit_improvements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 3 | `security_service_audit_improvement_id` | int | N |  | MUL |  | FK -> `security_service_audit_improvements`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `projects_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `security_service_id` | int | Y |  | MUL |  | FK -> `security_services`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `projects_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `third_party_risk_id` | int | Y |  | MUL |  | FK -> `third_party_risks`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---
