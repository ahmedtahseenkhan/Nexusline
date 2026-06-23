# 03. Business Organization (Units, Processes, Legal)

Organizational backbone: business units, business processes, legal/regulatory obligations and countries used across every other module.

**Tables in this module:** 10  ·  **Populated:** 0  ·  Back to [index](00-index.md)

**Table list:** `business_units`, `business_units_data_assets`, `business_units_legals`, `business_units_third_parties`, `business_units_vendor_assessments`, `countries`, `legals`, `legals_third_parties`, `processes`, `processes_third_parties`

---

### `business_units`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `workflow_status` | int | N | 0 |  |  |  |
| 5 | `workflow_owner_id` | int | Y |  |  |  |  |
| 6 | `_hidden` | int | N | 0 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |
| 9 | `edited` | datetime | Y |  |  |  |  |
| 10 | `deleted` | int | N | 0 |  |  |  |
| 11 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets`.asset_guardian_id, `assets`.asset_owner_id, `assets`.asset_user_id, `assets_business_units`.business_unit_id, `business_continuities_business_units`.business_unit_id, `business_units_legals`.business_unit_id, `business_units_third_parties`.business_unit_id, `business_units_vendor_assessments`.business_unit_id, `processes`.business_unit_id

---

### `business_units_data_assets`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_unit_id` | int | N |  |  |  | -> `business_units` *(inferred)* |
| 3 | `data_asset_id` | int | N |  |  |  | -> `data_assets` *(inferred)* |

---

### `business_units_legals`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |
| 3 | `legal_id` | int | N |  | MUL |  | FK -> `legals`.id |

---

### `business_units_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `business_units_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---

### `countries`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | Y |  |  |  |  |
| 3 | `model` | varchar(50) | N |  |  |  |  |
| 4 | `foreign_key` | int | N |  | MUL |  | -> polymorphic (see `model` column) |
| 5 | `country_id` | varchar(20) | N |  |  |  |  |

---

### `legals`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `risk_magnifier` | float | Y | 0 |  |  |  |
| 5 | `workflow_status` | int | N | 0 |  |  |  |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |
| 9 | `edited` | datetime | Y |  |  |  |  |
| 10 | `deleted` | int | N | 0 |  |  |  |
| 11 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_legals`.legal_id, `business_units_legals`.legal_id, `compliance_managements`.legal_id, `compliance_package_regulators_legals`.legal_id, `legals_third_parties`.legal_id

---

### `legals_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `legal_id` | int | N |  | MUL |  | FK -> `legals`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `processes`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |
| 3 | `name` | varchar(255) | N |  | MUL |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `rto` | int | Y |  |  |  |  |
| 6 | `rpo` | int | Y |  |  |  |  |
| 7 | `rpd` | int | Y |  |  |  |  |
| 8 | `workflow_status` | int | N | 0 |  |  |  |
| 9 | `workflow_owner_id` | int | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `edited` | datetime | Y |  |  |  |  |
| 13 | `deleted` | int | N | 0 |  |  |  |
| 14 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_processes`.process_id, `business_continuities_processes`.process_id, `processes_third_parties`.process_id

---

### `processes_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `process_id` | int | N |  | MUL |  | FK -> `processes`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---
