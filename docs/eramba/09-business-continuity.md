# 09. Business Continuity Management

Business Impact Analysis and Business Continuity Plans: BIA records, continuity plans, plan audits/tasks, threats/vulnerabilities and recovery objectives.

**Tables in this module:** 22  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `business_continuities`, `business_continuities_business_continuity_plans`, `business_continuities_business_units`, `business_continuities_compliance_managements`, `business_continuities_goals`, `business_continuities_processes`, `business_continuities_projects`, `business_continuities_risk_classifications`, `business_continuities_risk_exceptions`, `business_continuities_security_services`, `business_continuities_threats`, `business_continuities_vendor_assessments`, `business_continuities_vulnerabilities`, `business_continuity_plan_audit_dates`, `business_continuity_plan_audit_improvements`, `business_continuity_plan_audit_improvements_projects`, `business_continuity_plan_audit_improvements_security_incidents`, `business_continuity_plan_audit_result_options`, `business_continuity_plan_audits`, `business_continuity_plans`, `business_continuity_task_reminders`, `business_continuity_tasks`

---

### `business_continuities`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `impact` | text | N |  |  |  |  |
| 4 | `threats` | text | N |  |  |  |  |
| 5 | `vulnerabilities` | text | N |  |  |  |  |
| 6 | `description` | text | Y |  |  |  |  |
| 7 | `residual_score` | int | N |  |  |  |  |
| 8 | `risk_score` | float | Y |  |  |  |  |
| 9 | `risk_score_formula` | text | N |  |  |  |  |
| 10 | `residual_risk` | float | N |  |  |  |  |
| 11 | `residual_risk_formula` | text | N |  |  |  |  |
| 12 | `review` | date | N |  |  |  |  |
| 13 | `expired` | int | N | 0 |  |  |  |
| 14 | `exceptions_issues` | int | N | 0 |  |  |  |
| 15 | `controls_issues` | int | N | 0 |  |  |  |
| 16 | `control_in_design` | int | N | 0 |  |  |  |
| 17 | `expired_reviews` | int | N | 0 |  |  |  |
| 18 | `risk_above_appetite` | int | N | 0 |  |  |  |
| 19 | `plans_issues` | int | N | 0 |  |  |  |
| 20 | `risk_mitigation_strategy_id` | int | Y |  | MUL |  | FK -> `risk_mitigation_strategies`.id |
| 21 | `workflow_owner_id` | int | Y |  |  |  |  |
| 22 | `workflow_status` | int | N | 0 |  |  |  |
| 23 | `created` | datetime | N |  |  |  |  |
| 24 | `modified` | datetime | N |  |  |  |  |
| 25 | `edited` | datetime | Y |  |  |  |  |
| 26 | `deleted` | int | N | 0 |  |  |  |
| 27 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuities_business_continuity_plans`.business_continuity_id, `business_continuities_business_units`.business_continuity_id, `business_continuities_compliance_managements`.business_continuity_id, `business_continuities_goals`.business_continuity_id, `business_continuities_processes`.business_continuity_id, `business_continuities_projects`.business_continuity_id, `business_continuities_risk_classifications`.business_continuity_id, `business_continuities_risk_exceptions`.business_continuity_id, `business_continuities_threats`.business_continuity_id, `business_continuities_vendor_assessments`.business_continuity_id, `business_continuities_vulnerabilities`.business_continuity_id

---

### `business_continuities_business_continuity_plans`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `business_continuity_plan_id` | int | N |  | MUL |  | FK -> `business_continuity_plans`.id |

---

### `business_continuities_business_units`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |

---

### `business_continuities_compliance_managements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |

---

### `business_continuities_goals`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `goal_id` | int | N |  | MUL |  | FK -> `goals`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `business_continuities_processes`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `process_id` | int | N |  | MUL |  | FK -> `processes`.id |

---

### `business_continuities_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `business_continuity_id` | int | Y |  | MUL |  | FK -> `business_continuities`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `business_continuities_risk_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `risk_classification_id` | int | N |  | MUL |  | FK -> `risk_classifications`.id |
| 4 | `type` | int | N | 0 |  |  |  |
| 5 | `asset_classification_type_id` | int | Y |  | MUL |  | FK -> `asset_classification_types`.id |
| 6 | `group` | int | Y |  |  |  |  |
| 7 | `risk_classification_type_id` | int | Y |  | MUL |  | FK -> `risk_classification_types`.id |
| 8 | `ecb_type` | varchar(128) | Y |  |  |  |  |

---

### `business_continuities_risk_exceptions`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `risk_exception_id` | int | N |  | MUL |  | FK -> `risk_exceptions`.id |

---

### `business_continuities_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  |  |  | -> `business_continuities` *(inferred)* |
| 3 | `security_service_id` | int | N |  |  |  | -> `security_services` *(inferred)* |

---

### `business_continuities_threats`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `threat_id` | int | N |  | MUL |  | FK -> `threats`.id |

---

### `business_continuities_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---

### `business_continuities_vulnerabilities`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_id` | int | N |  | MUL |  | FK -> `business_continuities`.id |
| 3 | `vulnerability_id` | int | N |  | MUL |  | FK -> `vulnerabilities`.id |

---

### `business_continuity_plan_audit_dates`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_id` | int | N |  | MUL |  | FK -> `business_continuity_plans`.id |
| 3 | `day` | int | N |  |  |  |  |
| 4 | `month` | int | N |  |  |  |  |

---

### `business_continuity_plan_audit_improvements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_audit_id` | int | N |  | MUL |  | FK -> `business_continuity_plan_audits`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `business_continuity_plan_audit_improvements_projects`.business_continuity_plan_audit_improvement_id, `business_continuity_plan_audit_improvements_security_incidents`.business_continuity_plan_audit_improvement_id

---

### `business_continuity_plan_audit_improvements_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_audit_improvement_id` | int | N |  | MUL |  | FK -> `business_continuity_plan_audit_improvements`.id |
| 3 | `project_id` | int | N |  | MUL |  | FK -> `projects`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `business_continuity_plan_audit_improvements_security_incidents`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_audit_improvement_id` | int | N |  | MUL |  | FK -> `business_continuity_plan_audit_improvements`.id |
| 3 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `business_continuity_plan_audit_result_options`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(128) | Y |  |  |  |  |
| 3 | `hidden` | int | N | 0 |  |  |  |
| 4 | `editable` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuity_plan_audits`.business_continuity_plan_audit_result_option_id

**Configured values (2):**

| id | title | hidden | editable | created | modified |
|---|---|---|---|---|---|
| 1 | Failed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |
| 2 | Passed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |

---

### `business_continuity_plan_audits`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_id` | int | N |  | MUL |  | FK -> `business_continuity_plans`.id |
| 3 | `audit_metric_description` | text | N |  |  |  |  |
| 4 | `audit_success_criteria` | text | N |  |  |  |  |
| 5 | `result` | int | Y |  |  |  |  |
| 6 | `business_continuity_plan_audit_result_option_id` | int | Y |  | MUL |  | FK -> `business_continuity_plan_audit_result_options`.id |
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

**Referenced by (FK):** `business_continuity_plan_audit_improvements`.business_continuity_plan_audit_id

---

### `business_continuity_plans`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `objective` | text | N |  |  |  |  |
| 4 | `audit_metric` | text | N |  |  |  |  |
| 5 | `audit_success_criteria` | text | N |  |  |  |  |
| 6 | `launch_criteria` | text | N |  |  |  |  |
| 7 | `security_service_type_id` | int | Y |  | MUL |  | FK -> `security_service_types`.id |
| 8 | `opex` | float | N |  |  |  |  |
| 9 | `capex` | float | N |  |  |  |  |
| 10 | `resource_utilization` | int | N |  |  |  |  |
| 11 | `regular_review` | date | N |  |  |  |  |
| 12 | `awareness_recurrence` | varchar(150) | Y |  |  |  |  |
| 13 | `audit_calendar_type` | int | N | 0 |  |  |  |
| 14 | `audit_calendar_recurrence_start_date` | date | Y |  |  |  |  |
| 15 | `audit_calendar_recurrence_frequency` | int | Y |  |  |  |  |
| 16 | `audit_calendar_recurrence_period` | int | Y |  |  |  |  |
| 17 | `audits_all_done` | int | N |  |  |  |  |
| 18 | `audits_last_missing` | int | N |  |  |  |  |
| 19 | `audits_last_passed` | int | N |  |  |  |  |
| 20 | `audits_improvements` | int | N |  |  |  |  |
| 21 | `ongoing_corrective_actions` | int | N | 0 |  |  |  |
| 22 | `workflow_owner_id` | int | Y |  |  |  |  |
| 23 | `workflow_status` | int | N | 0 |  |  |  |
| 24 | `created` | datetime | N |  |  |  |  |
| 25 | `modified` | datetime | N |  |  |  |  |
| 26 | `edited` | datetime | Y |  |  |  |  |
| 27 | `deleted` | int | N | 0 |  |  |  |
| 28 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuities_business_continuity_plans`.business_continuity_plan_id, `business_continuity_plan_audit_dates`.business_continuity_plan_id, `business_continuity_plan_audits`.business_continuity_plan_id, `business_continuity_tasks`.business_continuity_plan_id

---

### `business_continuity_task_reminders`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_task_id` | int | N |  | MUL |  | FK -> `business_continuity_tasks`.id |
| 3 | `user_id` | int | N |  |  |  | -> `users` *(inferred)* |
| 4 | `seen` | tinyint(1) | N | 0 |  |  |  |
| 5 | `acknowledged` | tinyint(1) | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `business_continuity_tasks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_continuity_plan_id` | int | N |  | MUL |  | FK -> `business_continuity_plans`.id |
| 3 | `step` | int | N |  |  |  |  |
| 4 | `when` | text | N |  |  |  |  |
| 5 | `who` | text | N |  |  |  |  |
| 6 | `does` | text | N |  |  |  |  |
| 7 | `where` | text | N |  |  |  |  |
| 8 | `how` | text | N |  |  |  |  |
| 9 | `workflow_status` | int | N | 0 |  |  |  |
| 10 | `workflow_owner_id` | int | Y |  |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |
| 13 | `edited` | datetime | Y |  |  |  |  |
| 14 | `deleted` | int | N | 0 |  |  |  |
| 15 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuity_task_reminders`.business_continuity_task_id

---
