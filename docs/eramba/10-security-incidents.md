# 10. Security Incident Management

Security incident register: incidents, their classifications, lifecycle stages/statuses and links to controls, third parties and assets.

**Tables in this module:** 8  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `security_incident_classifications`, `security_incident_stages`, `security_incident_stages_security_incidents`, `security_incident_statuses`, `security_incidents`, `security_incidents_security_service_audit_improvements`, `security_incidents_security_services`, `security_incidents_third_parties`

---

### `security_incident_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `security_incidents`.security_incident_classification_id

---

### `security_incident_stages`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | Y |  |  |  |  |
| 4 | `workflow_owner_id` | int | Y |  |  |  |  |
| 5 | `workflow_status` | int | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `security_incident_stages_security_incidents`.security_incident_stage_id

---

### `security_incident_stages_security_incidents`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_incident_stage_id` | int | Y |  | MUL |  | FK -> `security_incident_stages`.id |
| 3 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 4 | `stage_name` | varchar(255) | Y |  |  |  |  |
| 5 | `stage_description` | text | Y |  |  |  |  |
| 6 | `status` | tinyint | N | 0 |  |  |  |
| 7 | `workflow_owner_id` | int | Y |  |  |  |  |
| 8 | `workflow_status` | int | N | 0 |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |
| 11 | `edited` | datetime | Y |  |  |  |  |

---

### `security_incident_statuses`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(100) | N |  |  |  |  |

**Referenced by (FK):** `security_incidents`.security_incident_status_id

**Configured values (2):**

| id | name |
|---|---|
| 2 | Ongoing |
| 3 | Closed |

---

### `security_incidents`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `reporter` | varchar(255) | N |  |  |  |  |
| 5 | `victim` | varchar(255) | N |  |  |  |  |
| 6 | `open_date` | date | N |  |  |  |  |
| 7 | `closure_date` | date | Y |  |  |  |  |
| 8 | `expired` | int | N | 0 |  |  |  |
| 9 | `type` | varchar(255) | N |  |  |  |  |
| 10 | `security_incident_status_id` | int | Y |  | MUL |  | FK -> `security_incident_statuses`.id |
| 11 | `auto_close_incident` | int | Y | 0 |  |  |  |
| 12 | `security_incident_classification_id` | int | Y |  | MUL |  | FK -> `security_incident_classifications`.id |
| 13 | `lifecycle_incomplete` | int | Y | 1 |  |  |  |
| 14 | `ongoing_incident` | int | N | 0 |  |  |  |
| 15 | `workflow_status` | int | N | 0 |  |  |  |
| 16 | `workflow_owner_id` | int | Y |  |  |  |  |
| 17 | `created` | datetime | N |  |  |  |  |
| 18 | `modified` | datetime | N |  |  |  |  |
| 19 | `edited` | datetime | Y |  |  |  |  |
| 20 | `deleted` | int | N | 0 |  |  |  |
| 21 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_security_incidents`.security_incident_id, `business_continuity_plan_audit_improvements_security_incidents`.security_incident_id, `goal_audit_improvements_security_incidents`.security_incident_id, `risks_security_incidents`.security_incident_id, `security_incident_classifications`.security_incident_id, `security_incident_stages_security_incidents`.security_incident_id, `security_incidents_security_service_audit_improvements`.security_incident_id, `security_incidents_security_services`.security_incident_id, `security_incidents_third_parties`.security_incident_id

---

### `security_incidents_security_service_audit_improvements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 3 | `security_service_audit_improvement_id` | int | N |  | MUL |  | FK -> `security_service_audit_improvements`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `security_incidents_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `security_incidents_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---
