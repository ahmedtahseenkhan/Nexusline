# 06. Internal Controls (Security Services)

Security services = internal controls catalogue: control definitions, classifications/types, audits, maintenances, issues, audit improvements and service contracts.

**Tables in this module:** 17  ·  **Populated:** 3  ·  Back to [index](00-index.md)

**Table list:** `security_service_audit_dates`, `security_service_audit_improvements`, `security_service_audit_result_options`, `security_service_audits`, `security_service_classifications`, `security_service_issues_security_services`, `security_service_maintenance_dates`, `security_service_maintenance_result_options`, `security_service_maintenances`, `security_service_security_service_audit_triggers`, `security_service_security_service_maintenance_triggers`, `security_service_types`, `security_services`, `security_services_service_contracts`, `security_services_third_party_risks`, `service_classifications`, `service_contracts`

---

### `security_service_audit_dates`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `day` | int | N |  |  |  |  |
| 4 | `month` | int | N |  |  |  |  |

---

### `security_service_audit_improvements`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_audit_id` | int | N |  | MUL |  | FK -> `security_service_audits`.id |
| 3 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `projects_security_service_audit_improvements`.security_service_audit_improvement_id, `security_incidents_security_service_audit_improvements`.security_service_audit_improvement_id

---

### `security_service_audit_result_options`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(128) | Y |  |  |  |  |
| 3 | `hidden` | int | N | 0 |  |  |  |
| 4 | `editable` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `security_service_audits`.security_service_audit_result_option_id

**Configured values (2):**

| id | title | hidden | editable | created | modified |
|---|---|---|---|---|---|
| 1 | Failed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |
| 2 | Passed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |

---

### `security_service_audits`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `audit_metric_description` | text | Y |  |  |  |  |
| 4 | `audit_success_criteria` | text | Y |  |  |  |  |
| 5 | `result` | int | Y |  |  |  |  |
| 6 | `security_service_audit_result_option_id` | int | Y |  | MUL |  | FK -> `security_service_audit_result_options`.id |
| 7 | `result_description` | text | N |  |  |  |  |
| 8 | `planned_date` | date | N |  |  |  |  |
| 9 | `start_date` | date | Y |  |  |  |  |
| 10 | `end_date` | date | Y |  |  |  |  |
| 11 | `workflow_owner_id` | int | Y |  |  |  |  |
| 12 | `workflow_status` | int | N | 0 |  |  |  |
| 13 | `created` | datetime | N |  |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |
| 15 | `edited` | datetime | Y |  |  |  |  |
| 16 | `deleted` | int | N | 0 |  |  |  |
| 17 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `security_service_audit_improvements`.security_service_audit_id

---

### `security_service_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `security_service_issues_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_issue_id` | int | N |  | MUL |  | FK -> `issues`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `security_service_maintenance_dates`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `day` | int | N |  |  |  |  |
| 4 | `month` | int | N |  |  |  |  |

---

### `security_service_maintenance_result_options`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(128) | Y |  |  |  |  |
| 3 | `hidden` | int | N | 0 |  |  |  |
| 4 | `editable` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `security_service_maintenances`.security_service_maintenance_result_option_id

**Configured values (2):**

| id | title | hidden | editable | created | modified |
|---|---|---|---|---|---|
| 1 | Failed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |
| 2 | Passed | 0 | 0 | 2025-12-10 13:09:05 | 2025-12-10 13:09:05 |

---

### `security_service_maintenances`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `task` | text | Y |  |  |  |  |
| 4 | `task_conclusion` | text | Y |  |  |  |  |
| 5 | `planned_date` | date | N |  |  |  |  |
| 6 | `start_date` | date | Y |  |  |  |  |
| 7 | `end_date` | date | Y |  |  |  |  |
| 8 | `result` | int | Y |  |  |  |  |
| 9 | `security_service_maintenance_result_option_id` | int | Y |  | MUL |  | FK -> `security_service_maintenance_result_options`.id |
| 10 | `workflow_owner_id` | int | Y |  |  |  |  |
| 11 | `workflow_status` | int | N | 0 |  |  |  |
| 12 | `created` | datetime | N |  |  |  |  |
| 13 | `modified` | datetime | N |  |  |  |  |
| 14 | `edited` | datetime | Y |  |  |  |  |
| 15 | `deleted` | int | N | 0 |  |  |  |
| 16 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `security_service_security_service_audit_triggers`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `security_service_audit_trigger_id` | int | N |  | MUL |  | FK -> `triggers`.id |

---

### `security_service_security_service_maintenance_triggers`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `security_service_maintenance_trigger_id` | int | N |  | MUL |  | FK -> `triggers`.id |

---

### `security_service_types`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `business_continuity_plans`.security_service_type_id, `security_services`.security_service_type_id

**Configured values (2):**

| id | name |
|---|---|
| 2 | Design |
| 4 | Production |

---

### `security_services`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `objective` | text | N |  |  |  |  |
| 4 | `security_service_type_id` | int | Y |  | MUL |  | FK -> `security_service_types`.id |
| 5 | `service_classification_id` | int | Y |  | MUL |  | FK -> `service_classifications`.id |
| 6 | `documentation_url` | text | N |  |  |  |  |
| 7 | `audit_calendar_type` | int | N | 0 |  |  |  |
| 8 | `audit_calendar_mode` | int | N | 1 |  |  |  |
| 9 | `audit_calendar_recurrence_start_date` | date | Y |  |  |  |  |
| 10 | `audit_calendar_recurrence_frequency` | int | Y |  |  |  |  |
| 11 | `audit_calendar_recurrence_period` | int | Y |  |  |  |  |
| 12 | `maintenance_calendar_type` | int | N | 0 |  |  |  |
| 13 | `maintenance_calendar_mode` | int | N | 1 |  |  |  |
| 14 | `audit_execution` | int | N | 0 |  |  |  |
| 15 | `maintenance_execution` | int | N | 0 |  |  |  |
| 16 | `maintenance_calendar_recurrence_start_date` | date | Y |  |  |  |  |
| 17 | `maintenance_calendar_recurrence_frequency` | int | Y |  |  |  |  |
| 18 | `maintenance_calendar_recurrence_period` | int | Y |  |  |  |  |
| 19 | `audit_metric_description` | text | Y |  |  |  |  |
| 20 | `audit_success_criteria` | text | Y |  |  |  |  |
| 21 | `maintenance_metric_description` | text | Y |  |  |  |  |
| 22 | `opex` | float | Y |  |  |  |  |
| 23 | `capex` | float | Y |  |  |  |  |
| 24 | `resource_utilization` | int | Y |  |  |  |  |
| 25 | `audits_all_done` | int | N |  |  |  |  |
| 26 | `audits_not_all_done` | int | N |  |  |  |  |
| 27 | `audits_last_missing` | int | N |  |  |  |  |
| 28 | `audits_last_passed` | int | N |  |  |  |  |
| 29 | `audits_improvements` | int | N |  |  |  |  |
| 30 | `audits_status` | int | N |  |  |  |  |
| 31 | `maintenances_all_done` | int | N |  |  |  |  |
| 32 | `maintenances_not_all_done` | int | N |  |  |  |  |
| 33 | `maintenances_last_missing` | int | N |  |  |  |  |
| 34 | `maintenances_last_passed` | int | N |  |  |  |  |
| 35 | `ongoing_security_incident` | int | N | 0 |  |  |  |
| 36 | `security_incident_open_count` | int | N |  |  |  |  |
| 37 | `control_with_issues` | int | N | 0 |  |  |  |
| 38 | `ongoing_corrective_actions` | int | N | 0 |  |  |  |
| 39 | `workflow_owner_id` | int | Y |  |  |  |  |
| 40 | `workflow_status` | int | N | 0 |  |  |  |
| 41 | `created` | datetime | N |  |  |  |  |
| 42 | `modified` | datetime | N |  |  |  |  |
| 43 | `edited` | datetime | Y |  |  |  |  |
| 44 | `deleted` | int | N | 0 |  |  |  |
| 45 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_managements_security_services`.security_service_id, `data_assets_security_services`.security_service_id, `goals_security_services`.security_service_id, `projects_security_services`.security_service_id, `risks_security_services`.security_service_id, `security_incidents_security_services`.security_service_id, `security_policies_security_services`.security_service_id, `security_service_audit_dates`.security_service_id, `security_service_audits`.security_service_id, `security_service_classifications`.security_service_id, `security_service_issues_security_services`.security_service_id, `security_service_maintenance_dates`.security_service_id, `security_service_maintenances`.security_service_id, `security_service_security_service_audit_triggers`.security_service_id, `security_service_security_service_maintenance_triggers`.security_service_id, `security_services_service_contracts`.security_service_id, `security_services_third_party_risks`.security_service_id

---

### `security_services_service_contracts`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `service_contract_id` | int | N |  | MUL |  | FK -> `service_contracts`.id |

---

### `security_services_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |

---

### `service_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `workflow_owner_id` | int | Y |  |  |  |  |
| 5 | `workflow_status` | int | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `security_services`.service_classification_id

---

### `service_contracts`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `value` | int | N |  |  |  |  |
| 6 | `start` | date | N |  |  |  |  |
| 7 | `end` | date | Y |  |  |  |  |
| 8 | `expired` | int | N | 0 |  |  |  |
| 9 | `workflow_owner_id` | int | Y |  |  |  |  |
| 10 | `workflow_status` | int | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |
| 13 | `edited` | datetime | Y |  |  |  |  |
| 14 | `deleted` | int | N | 0 |  |  |  |
| 15 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `security_services_service_contracts`.service_contract_id

---
