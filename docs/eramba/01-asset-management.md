# 01. Asset Management

Asset Identification register: physical/logical assets, their classifications (CIA), media types, labels, owners and links to risks, processes, legal and business units.

**Tables in this module:** 18  ·  **Populated:** 3  ·  Back to [index](00-index.md)

**Table list:** `asset_classification_types`, `asset_classifications`, `asset_classifications_assets`, `asset_labels`, `asset_media_types`, `asset_media_types_threats`, `asset_media_types_vulnerabilities`, `assets`, `assets_business_units`, `assets_compliance_managements`, `assets_legals`, `assets_policy_exceptions`, `assets_processes`, `assets_related`, `assets_risks`, `assets_security_incidents`, `assets_third_party_risks`, `assets_vendor_assessments`

---

### `asset_classification_types`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `asset_classification_count` | int | N |  |  |  |  |

**Referenced by (FK):** `asset_classifications`.asset_classification_type_id, `asset_classifications_assets`.asset_classification_type_id, `business_continuities_risk_classifications`.asset_classification_type_id, `risk_classifications_risks`.asset_classification_type_id, `risk_classifications_third_party_risks`.asset_classification_type_id, `risk_score_risk_classifications`.asset_classification_type_id

---

### `asset_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `criteria` | text | N |  |  |  |  |
| 4 | `value` | float | Y |  |  |  |  |
| 5 | `asset_classification_type_id` | int | N |  | MUL |  | FK -> `asset_classification_types`.id |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `asset_classifications_assets`.asset_classification_id

---

### `asset_classifications_assets`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_classification_id` | int | N |  | MUL |  | FK -> `asset_classifications`.id |
| 3 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 4 | `asset_classification_type_id` | int | Y |  | MUL |  | FK -> `asset_classification_types`.id |

---

### `asset_labels`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `workflow_owner_id` | int | Y |  |  |  |  |
| 5 | `workflow_status` | int | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `assets`.asset_label_id, `security_policies`.asset_label_id

---

### `asset_media_types`

*Rows: 8*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(100) | N |  | MUL |  |  |
| 3 | `editable` | int | Y | 0 |  |  |  |
| 4 | `created` | datetime | Y |  |  |  |  |
| 5 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `asset_media_types_threats`.asset_media_type_id, `asset_media_types_vulnerabilities`.asset_media_type_id, `assets`.asset_media_type_id

**Configured values (8):**

| id | name | editable | created | modified |
|---|---|---|---|---|
| 1 | Data Asset | 0 |  |  |
| 2 | Facilities | 0 |  |  |
| 3 | People | 0 |  |  |
| 4 | Hardware | 0 |  |  |
| 5 | Software | 0 |  |  |
| 6 | IT Service | 0 |  |  |
| 7 | Network | 0 |  |  |
| 8 | Financial | 0 |  |  |

---

### `asset_media_types_threats`

*Rows: 72 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_media_type_id` | int | N |  | MUL |  | FK -> `asset_media_types`.id |
| 3 | `threat_id` | int | N |  | MUL |  | FK -> `threats`.id |

---

### `asset_media_types_vulnerabilities`

*Rows: 11 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_media_type_id` | int | N |  | MUL |  | FK -> `asset_media_types`.id |
| 3 | `vulnerability_id` | int | N |  | MUL |  | FK -> `vulnerabilities`.id |

---

### `assets`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `asset_label_id` | int | Y |  | MUL |  | FK -> `asset_labels`.id |
| 5 | `asset_media_type_id` | int | Y |  | MUL |  | FK -> `asset_media_types`.id |
| 6 | `asset_owner_id` | int | Y |  | MUL |  | FK -> `business_units`.id |
| 7 | `asset_guardian_id` | int | Y |  | MUL |  | FK -> `business_units`.id |
| 8 | `asset_user_id` | int | Y |  | MUL |  | FK -> `business_units`.id |
| 9 | `review` | date | N |  |  |  |  |
| 10 | `expired_reviews` | int | N | 0 |  |  |  |
| 11 | `security_incident_open_count` | int | N |  |  |  |  |
| 12 | `workflow_owner_id` | int | Y |  |  |  |  |
| 13 | `workflow_status` | int | N | 0 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `edited` | datetime | Y |  |  |  |  |
| 17 | `deleted` | int | N | 0 |  |  |  |
| 18 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_reviews_assets`.asset_id, `asset_classifications_assets`.asset_id, `assets_business_units`.asset_id, `assets_compliance_managements`.asset_id, `assets_legals`.asset_id, `assets_policy_exceptions`.asset_id, `assets_processes`.asset_id, `assets_related`.asset_id, `assets_related`.asset_related_id, `assets_risks`.asset_id, `assets_security_incidents`.asset_id, `assets_third_party_risks`.asset_id, `assets_vendor_assessments`.asset_id, `data_asset_instances`.asset_id

---

### `assets_business_units`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `business_unit_id` | int | N |  | MUL |  | FK -> `business_units`.id |

---

### `assets_compliance_managements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |

---

### `assets_legals`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `legal_id` | int | N |  | MUL |  | FK -> `legals`.id |

---

### `assets_policy_exceptions`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `policy_exception_id` | int | N |  | MUL |  | FK -> `policy_exceptions`.id |

---

### `assets_processes`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `process_id` | int | N |  | MUL |  | FK -> `processes`.id |

---

### `assets_related`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `asset_related_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `assets_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |

---

### `assets_security_incidents`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `assets_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |

---

### `assets_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---
