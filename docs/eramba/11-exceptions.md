# 11. Exceptions Management

Risk, policy and compliance exceptions — formal sign-off that a control gap or non-conformity is knowingly accepted for a period.

**Tables in this module:** 10  ·  **Populated:** 0  ·  Back to [index](00-index.md)

**Table list:** `compliance_exceptions`, `compliance_exceptions_compliance_findings`, `compliance_exceptions_compliance_managements`, `policy_exception_classifications`, `policy_exceptions`, `policy_exceptions_security_policies`, `policy_exceptions_third_parties`, `risk_exceptions`, `risk_exceptions_risks`, `risk_exceptions_third_party_risks`

---

### `compliance_exceptions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `start_date` | date | Y |  |  |  |  |
| 5 | `expiration` | date | N |  |  |  |  |
| 6 | `expired` | int | N | 0 |  |  |  |
| 7 | `closure_date_toggle` | tinyint(1) | N | 1 |  |  |  |
| 8 | `closure_date` | date | Y |  |  |  |  |
| 9 | `status` | int | N |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `edited` | datetime | Y |  |  |  |  |
| 13 | `deleted` | int | N | 0 |  |  |  |
| 14 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_exceptions_compliance_findings`.compliance_exception_id, `compliance_exceptions_compliance_managements`.compliance_exception_id

---

### `compliance_exceptions_compliance_findings`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_exception_id` | int | N |  | MUL |  | FK -> `compliance_exceptions`.id |
| 3 | `compliance_finding_id` | int | N |  | MUL |  | FK -> `compliance_findings`.id |

---

### `compliance_exceptions_compliance_managements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_exception_id` | int | N |  | MUL |  | FK -> `compliance_exceptions`.id |
| 3 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |

---

### `policy_exception_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `policy_exception_id` | int | N |  | MUL |  | FK -> `policy_exceptions`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `policy_exceptions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `start_date` | date | Y |  |  |  |  |
| 5 | `expiration` | date | N |  |  |  |  |
| 6 | `expired` | int | N | 0 |  |  |  |
| 7 | `closure_date_toggle` | tinyint(1) | N | 1 |  |  |  |
| 8 | `closure_date` | date | Y |  |  |  |  |
| 9 | `status` | int | N |  |  |  |  |
| 10 | `workflow_owner_id` | int | Y |  |  |  |  |
| 11 | `workflow_status` | int | N | 0 |  |  |  |
| 12 | `created` | datetime | N |  |  |  |  |
| 13 | `modified` | datetime | N |  |  |  |  |
| 14 | `edited` | datetime | Y |  |  |  |  |
| 15 | `deleted` | int | N | 0 |  |  |  |
| 16 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_policy_exceptions`.policy_exception_id, `policy_exception_classifications`.policy_exception_id, `policy_exceptions_security_policies`.policy_exception_id, `policy_exceptions_third_parties`.policy_exception_id

---

### `policy_exceptions_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `policy_exception_id` | int | N |  | MUL |  | FK -> `policy_exceptions`.id |
| 3 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |

---

### `policy_exceptions_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `policy_exception_id` | int | N |  | MUL |  | FK -> `policy_exceptions`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `risk_exceptions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `start_date` | date | Y |  |  |  |  |
| 5 | `expiration` | date | N |  |  |  |  |
| 6 | `expired` | int | N | 0 |  |  |  |
| 7 | `closure_date_toggle` | tinyint(1) | N | 1 |  |  |  |
| 8 | `closure_date` | date | Y |  |  |  |  |
| 9 | `status` | int | N |  |  |  |  |
| 10 | `workflow_owner_id` | int | Y |  |  |  |  |
| 11 | `workflow_status` | int | N | 0 |  |  |  |
| 12 | `created` | datetime | N |  |  |  |  |
| 13 | `modified` | datetime | N |  |  |  |  |
| 14 | `edited` | datetime | Y |  |  |  |  |
| 15 | `deleted` | int | N | 0 |  |  |  |
| 16 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_continuities_risk_exceptions`.risk_exception_id, `risk_exceptions_risks`.risk_exception_id

---

### `risk_exceptions_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 3 | `risk_exception_id` | int | N |  | MUL |  | FK -> `risk_exceptions`.id |

---

### `risk_exceptions_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_exception_id` | int | N |  |  |  | -> `risk_exceptions` *(inferred)* |
| 3 | `third_party_risk_id` | int | N |  |  |  | -> `third_party_risks` *(inferred)* |

---
