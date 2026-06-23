# 04. Risk Management

Core risk register: risk identification & analysis, classifications/appetite/scoring, calculation methods, threats, vulnerabilities, mitigation strategies and treatment.

**Tables in this module:** 26  ·  **Populated:** 5  ·  Back to [index](00-index.md)

**Table list:** `risk_appetite_threshold_risk_classification_types`, `risk_appetite_threshold_risk_classifications`, `risk_appetite_thresholds`, `risk_appetite_thresholds_risks`, `risk_appetites`, `risk_appetites_risk_classification_types`, `risk_calculation_values`, `risk_calculations`, `risk_classification_types`, `risk_classifications`, `risk_classifications_risks`, `risk_classifications_third_party_risks`, `risk_mitigation_strategies`, `risk_overtime_graphs`, `risk_score_risk_classifications`, `risk_score_value_logs`, `risk_scores`, `risks`, `risks_security_incidents`, `risks_security_policies`, `risks_security_services`, `risks_threats`, `risks_vendor_assessments`, `risks_vulnerabilities`, `threats`, `vulnerabilities`

---

### `risk_appetite_threshold_risk_classification_types`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_appetite_threshold_id` | int | N |  | MUL |  | FK -> `risk_appetite_thresholds`.id |
| 3 | `risk_classification_type_id` | int | N |  | MUL |  | FK -> `risk_classification_types`.id |

---

### `risk_appetite_threshold_risk_classifications`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_appetite_threshold_id` | int | N |  | MUL |  | FK -> `risk_appetite_thresholds`.id |
| 3 | `risk_classification_id` | int | N |  | MUL |  | FK -> `risk_classifications`.id |

---

### `risk_appetite_thresholds`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_appetite_id` | int | N |  | MUL |  | FK -> `risk_appetites`.id |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `color` | text | N |  |  |  |  |
| 6 | `type` | int | N | 1 |  |  |  |
| 7 | `classifications_key` | varchar(255) | Y |  |  |  |  |
| 8 | `classification_types_key` | varchar(255) | Y |  |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `risk_appetite_threshold_risk_classification_types`.risk_appetite_threshold_id, `risk_appetite_threshold_risk_classifications`.risk_appetite_threshold_id, `risk_appetite_thresholds_risks`.risk_appetite_threshold_id

---

### `risk_appetite_thresholds_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `risk_appetite_threshold_id` | int | N |  | MUL |  | FK -> `risk_appetite_thresholds`.id |
| 5 | `type` | int | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `risk_appetites`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `method` | int | Y |  |  |  |  |
| 4 | `risk_appetite` | int | N | 0 |  |  |  |
| 5 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `risk_appetite_thresholds`.risk_appetite_id, `risk_appetites_risk_classification_types`.risk_appetite_id

**Configured values (3):**

| id | model | method | risk_appetite | modified |
|---|---|---|---|---|
| 1 | Risks |  | 1 | 2020-03-13 10:52:18 |
| 2 | ThirdPartyRisks |  | 1 | 2020-03-13 10:52:18 |
| 3 | BusinessContinuities |  | 1 | 2020-03-13 10:52:18 |

---

### `risk_appetites_risk_classification_types`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_appetite_id` | int | N |  | MUL |  | FK -> `risk_appetites`.id |
| 3 | `risk_classification_type_id` | int | N |  | MUL |  | FK -> `risk_classification_types`.id |

---

### `risk_calculation_values`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_calculation_id` | int | N |  | MUL |  | FK -> `risk_calculations`.id |
| 3 | `field` | varchar(255) | N |  |  |  |  |
| 4 | `value` | int | N |  | MUL |  | FK -> `risk_classification_types`.id |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `risk_calculations`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `method` | varchar(255) | Y |  |  |  |  |
| 4 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `risk_calculation_values`.risk_calculation_id

**Configured values (3):**

| id | model | method | modified |
|---|---|---|---|
| 1 | Risks |  | 2016-11-18 14:38:23 |
| 2 | ThirdPartyRisks |  | 2016-11-18 14:38:23 |
| 3 | BusinessContinuities |  | 2016-11-18 14:38:23 |

---

### `risk_classification_types`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `risk_classification_count` | int | N |  |  |  |  |

**Referenced by (FK):** `business_continuities_risk_classifications`.risk_classification_type_id, `risk_appetite_threshold_risk_classification_types`.risk_classification_type_id, `risk_appetites_risk_classification_types`.risk_classification_type_id, `risk_calculation_values`.value, `risk_classifications`.risk_classification_type_id, `risk_classifications_risks`.risk_classification_type_id, `risk_classifications_third_party_risks`.risk_classification_type_id, `risk_scores`.risk_classification_type_id

---

### `risk_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `criteria` | text | N |  |  |  |  |
| 4 | `value` | float | Y |  |  |  |  |
| 5 | `risk_classification_type_id` | int | Y |  | MUL |  | FK -> `risk_classification_types`.id |
| 6 | `workflow_owner_id` | int | Y |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `business_continuities_risk_classifications`.risk_classification_id, `risk_appetite_threshold_risk_classifications`.risk_classification_id, `risk_classifications_risks`.risk_classification_id, `risk_classifications_third_party_risks`.risk_classification_id, `risk_score_risk_classifications`.risk_classification_id

---

### `risk_classifications_risks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_classification_id` | int | N |  | MUL |  | FK -> `risk_classifications`.id |
| 3 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 4 | `type` | int | N | 0 |  |  |  |
| 5 | `asset_classification_type_id` | int | Y |  | MUL |  | FK -> `asset_classification_types`.id |
| 6 | `group` | int | Y |  |  |  |  |
| 7 | `risk_classification_type_id` | int | Y |  | MUL |  | FK -> `risk_classification_types`.id |
| 8 | `ecb_type` | varchar(128) | Y |  |  |  |  |

---

### `risk_classifications_third_party_risks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_classification_id` | int | N |  | MUL |  | FK -> `risk_classifications`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 4 | `type` | int | N | 0 |  |  |  |
| 5 | `asset_classification_type_id` | int | Y |  | MUL |  | FK -> `asset_classification_types`.id |
| 6 | `group` | int | Y |  |  |  |  |
| 7 | `risk_classification_type_id` | int | Y |  | MUL |  | FK -> `risk_classification_types`.id |
| 8 | `ecb_type` | varchar(128) | Y |  |  |  |  |

---

### `risk_mitigation_strategies`

*Rows: 4*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `business_continuities`.risk_mitigation_strategy_id, `risks`.risk_mitigation_strategy_id, `third_party_risks`.risk_mitigation_strategy_id

**Configured values (4):**

| id | name |
|---|---|
| 1 | Accept |
| 2 | Avoid |
| 3 | Mitigate |
| 4 | Transfer |

---

### `risk_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_count` | int | N |  |  |  |  |
| 3 | `risk_score` | int | N |  |  |  |  |
| 4 | `residual_score` | int | N |  |  |  |  |
| 5 | `timestamp` | varchar(45) | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `risk_score_risk_classifications`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_score_id` | int | N |  | MUL |  | FK -> `risk_scores`.id |
| 3 | `risk_classification_id` | int | N |  | MUL |  | FK -> `risk_classifications`.id |
| 4 | `asset_classification_type_id` | int | Y |  | MUL |  | FK -> `asset_classification_types`.id |

---

### `risk_score_value_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_score_id` | int | N |  | MUL |  | FK -> `risk_scores`.id |
| 3 | `field` | varchar(256) | N |  |  |  |  |
| 4 | `value` | float | N | 0 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `risk_scores`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `score` | float | Y |  |  |  |  |
| 5 | `formula` | text | Y |  |  |  |  |
| 6 | `type` | int | N |  |  |  |  |
| 7 | `classifications_key` | text | Y |  |  |  |  |
| 8 | `classification_types_key` | text | Y |  |  |  |  |
| 9 | `risk_classification_type_id` | int | Y |  | MUL |  | FK -> `risk_classification_types`.id |

**Referenced by (FK):** `risk_score_risk_classifications`.risk_score_id, `risk_score_value_logs`.risk_score_id

---

### `risks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `threats` | text | N |  |  |  |  |
| 4 | `vulnerabilities` | text | N |  |  |  |  |
| 5 | `description` | text | Y |  |  |  |  |
| 6 | `residual_score` | int | N |  |  |  |  |
| 7 | `risk_score` | float | Y |  |  |  |  |
| 8 | `risk_score_formula` | text | N |  |  |  |  |
| 9 | `residual_risk` | float | N |  |  |  |  |
| 10 | `residual_risk_formula` | text | N |  |  |  |  |
| 11 | `review` | date | N |  |  |  |  |
| 12 | `expired` | int | N | 0 |  |  |  |
| 13 | `exceptions_issues` | int | N | 0 |  |  |  |
| 14 | `controls_issues` | int | N | 0 |  |  |  |
| 15 | `control_in_design` | int | N | 0 |  |  |  |
| 16 | `expired_reviews` | int | N | 0 |  |  |  |
| 17 | `risk_above_appetite` | int | N | 0 |  |  |  |
| 18 | `risk_mitigation_strategy_id` | int | Y |  | MUL |  | FK -> `risk_mitigation_strategies`.id |
| 19 | `workflow_owner_id` | int | Y |  |  |  |  |
| 20 | `workflow_status` | int | N | 0 |  |  |  |
| 21 | `created` | datetime | N |  |  |  |  |
| 22 | `modified` | datetime | N |  |  |  |  |
| 23 | `edited` | datetime | Y |  |  |  |  |
| 24 | `deleted` | int | N | 0 |  |  |  |
| 25 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_risks`.risk_id, `compliance_managements_risks`.risk_id, `goals_risks`.risk_id, `projects_risks`.risk_id, `risk_classifications_risks`.risk_id, `risk_exceptions_risks`.risk_id, `risks_security_services`.risk_id, `risks_threats`.risk_id, `risks_vendor_assessments`.risk_id, `risks_vulnerabilities`.risk_id

---

### `risks_security_incidents`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  |  |  | -> `risks` *(inferred)* |
| 3 | `security_incident_id` | int | N |  | MUL |  | FK -> `security_incidents`.id |
| 4 | `risk_type` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `risks_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  |  |  | -> `risks` *(inferred)* |
| 3 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 4 | `type` | varchar(50) | N | treatment |  |  |  |
| 5 | `risk_type` | varchar(255) | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `risks_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `risks_threats`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 3 | `threat_id` | int | N |  | MUL |  | FK -> `threats`.id |

---

### `risks_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---

### `risks_vulnerabilities`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |
| 3 | `vulnerability_id` | int | N |  | MUL |  | FK -> `vulnerabilities`.id |

---

### `threats`

*Rows: 34*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |

**Referenced by (FK):** `asset_media_types_threats`.threat_id, `business_continuities_threats`.threat_id, `risks_threats`.threat_id, `third_party_risks_threats`.threat_id

---

### `vulnerabilities`

*Rows: 34*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |

**Referenced by (FK):** `asset_media_types_vulnerabilities`.vulnerability_id, `business_continuities_vulnerabilities`.vulnerability_id, `risks_vulnerabilities`.vulnerability_id, `third_party_risks_vulnerabilities`.vulnerability_id

---
