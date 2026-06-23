# 05. Third-Party Risk & Vendor Assessments

Third parties (vendors), third-party risks, and vendor self-assessment questionnaires/findings used to evaluate suppliers.

**Tables in this module:** 22  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `third_parties`, `third_parties_third_party_risks`, `third_parties_vendor_assessments`, `third_party_audit_overtime_graphs`, `third_party_incident_overtime_graphs`, `third_party_overtime_graphs`, `third_party_risk_overtime_graphs`, `third_party_risks`, `third_party_risks_threats`, `third_party_risks_vendor_assessments`, `third_party_risks_vulnerabilities`, `third_party_types`, `vendor_assessment_feedbacks`, `vendor_assessment_feedbacks_vendor_assessment_options`, `vendor_assessment_files`, `vendor_assessment_findings`, `vendor_assessment_findings_questions`, `vendor_assessment_option_triggers`, `vendor_assessment_options`, `vendor_assessment_questionnaires`, `vendor_assessment_questions`, `vendor_assessments`

---

### `third_parties`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `third_party_type_id` | int | Y |  | MUL |  | FK -> `third_party_types`.id |
| 5 | `security_incident_count` | int | N | 0 |  |  |  |
| 6 | `security_incident_open_count` | int | N | 0 |  |  |  |
| 7 | `service_contract_count` | int | N | 0 |  |  |  |
| 8 | `workflow_status` | int | N | 0 |  |  |  |
| 9 | `workflow_owner_id` | int | Y |  |  |  |  |
| 10 | `_hidden` | int | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |
| 13 | `edited` | datetime | Y |  |  |  |  |
| 14 | `deleted` | int | N | 0 |  |  |  |
| 15 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `business_units_third_parties`.third_party_id, `compliance_audits`.third_party_id, `data_asset_settings_third_parties`.third_party_id, `data_assets_third_parties`.third_party_id, `legals_third_parties`.third_party_id, `policy_exceptions_third_parties`.third_party_id, `processes_third_parties`.third_party_id, `security_incidents_third_parties`.third_party_id, `service_contracts`.third_party_id, `third_parties_third_party_risks`.third_party_id, `third_parties_vendor_assessments`.third_party_id, `third_party_audit_overtime_graphs`.third_party_id, `third_party_incident_overtime_graphs`.third_party_id, `third_party_overtime_graphs`.third_party_id

---

### `third_parties_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `third_parties_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---

### `third_party_audit_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 3 | `open` | int | Y |  |  |  |  |
| 4 | `closed` | int | Y |  |  |  |  |
| 5 | `expired` | int | Y |  |  |  |  |
| 6 | `no_evidence` | int | N |  |  |  |  |
| 7 | `waiting_evidence` | int | N |  |  |  |  |
| 8 | `provided_evidence` | int | N |  |  |  |  |
| 9 | `timestamp` | varchar(45) | N |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `third_party_incident_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 3 | `security_incident_count` | int | N |  |  |  |  |
| 4 | `timestamp` | varchar(45) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `third_party_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 3 | `no_controls` | int | N |  |  |  |  |
| 4 | `failed_controls` | int | N |  |  |  |  |
| 5 | `ok_controls` | int | N |  |  |  |  |
| 6 | `average_effectiveness` | int | N |  |  |  |  |
| 7 | `timestamp` | varchar(45) | N |  |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |

---

### `third_party_risk_overtime_graphs`

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

### `third_party_risks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `shared_information` | text | N |  |  |  |  |
| 4 | `controlled` | text | N |  |  |  |  |
| 5 | `threats` | text | N |  |  |  |  |
| 6 | `vulnerabilities` | text | N |  |  |  |  |
| 7 | `description` | text | Y |  |  |  |  |
| 8 | `residual_score` | int | N |  |  |  |  |
| 9 | `risk_score` | float | Y |  |  |  |  |
| 10 | `risk_score_formula` | text | N |  |  |  |  |
| 11 | `residual_risk` | float | N |  |  |  |  |
| 12 | `residual_risk_formula` | text | N |  |  |  |  |
| 13 | `review` | date | N |  |  |  |  |
| 14 | `expired` | int | N | 0 |  |  |  |
| 15 | `exceptions_issues` | int | N | 0 |  |  |  |
| 16 | `controls_issues` | int | N | 0 |  |  |  |
| 17 | `control_in_design` | int | N | 0 |  |  |  |
| 18 | `expired_reviews` | int | N | 0 |  |  |  |
| 19 | `risk_above_appetite` | int | N | 0 |  |  |  |
| 20 | `risk_mitigation_strategy_id` | int | Y |  | MUL |  | FK -> `risk_mitigation_strategies`.id |
| 21 | `workflow_owner_id` | int | Y |  |  |  |  |
| 22 | `workflow_status` | int | N | 0 |  |  |  |
| 23 | `created` | datetime | N |  |  |  |  |
| 24 | `modified` | datetime | N |  |  |  |  |
| 25 | `edited` | datetime | Y |  |  |  |  |
| 26 | `deleted` | int | N | 0 |  |  |  |
| 27 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_third_party_risks`.third_party_risk_id, `compliance_findings_third_party_risks`.third_party_risk_id, `compliance_managements_third_party_risks`.third_party_risk_id, `goals_third_party_risks`.third_party_risk_id, `projects_third_party_risks`.third_party_risk_id, `risk_classifications_third_party_risks`.third_party_risk_id, `security_services_third_party_risks`.third_party_risk_id, `third_parties_third_party_risks`.third_party_risk_id, `third_party_risks_threats`.third_party_risk_id, `third_party_risks_vendor_assessments`.third_party_risk_id, `third_party_risks_vulnerabilities`.third_party_risk_id

---

### `third_party_risks_threats`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 3 | `threat_id` | int | N |  | MUL |  | FK -> `threats`.id |

---

### `third_party_risks_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---

### `third_party_risks_vulnerabilities`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |
| 3 | `vulnerability_id` | int | N |  | MUL |  | FK -> `vulnerabilities`.id |

---

### `third_party_types`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `third_parties`.third_party_type_id

**Configured values (3):**

| id | name |
|---|---|
| 1 | Customers |
| 2 | Suppliers |
| 3 | Regulators |

---

### `vendor_assessment_feedbacks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |
| 3 | `vendor_assessment_question_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questions`.id |
| 4 | `vendor_assessment_option_id` | int | Y |  | MUL |  | FK -> `vendor_assessment_options`.id |
| 5 | `answer` | text | N |  |  |  |  |
| 6 | `answer_date` | datetime | Y |  |  |  |  |
| 7 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 8 | `last_answer_date` | datetime | Y |  |  |  |  |
| 9 | `completed` | int | N | 0 |  |  |  |
| 10 | `score` | decimal(11,4) | N | 0.0000 |  |  |  |
| 11 | `locked` | int | N | 0 |  |  |  |
| 12 | `hidden` | int | N | 0 |  |  |  |
| 13 | `created` | datetime | N |  |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |
| 15 | `edited` | datetime | Y |  |  |  |  |
| 16 | `deleted` | int | N | 0 |  |  |  |
| 17 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_feedbacks_vendor_assessment_options`.vendor_assessment_feedback_id

---

### `vendor_assessment_feedbacks_vendor_assessment_options`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_feedback_id` | int | N |  | MUL |  | FK -> `vendor_assessment_feedbacks`.id |
| 3 | `vendor_assessment_option_id` | int | N |  | MUL |  | FK -> `vendor_assessment_options`.id |

---

### `vendor_assessment_files`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `filename` | varchar(255) | N |  |  |  |  |
| 3 | `created` | datetime | N |  |  |  |  |
| 4 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_questionnaires`.vendor_assessment_file_id

---

### `vendor_assessment_findings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `deadline` | date | N |  |  |  |  |
| 6 | `start_date` | date | Y |  |  |  |  |
| 7 | `close_date` | date | Y |  |  |  |  |
| 8 | `auto_close_date` | int | N | 1 |  |  |  |
| 9 | `status` | int | N |  |  |  |  |
| 10 | `expired` | int | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |
| 13 | `edited` | datetime | Y |  |  |  |  |
| 14 | `deleted` | int | N | 0 |  |  |  |
| 15 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_findings_questions`.vendor_assessment_finding_id

---

### `vendor_assessment_findings_questions`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_finding_id` | int | N |  | MUL |  | FK -> `vendor_assessment_findings`.id |
| 3 | `vendor_assessment_question_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questions`.id |

---

### `vendor_assessment_option_triggers`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 1 |  |  |  |
| 3 | `vendor_assessment_option_id` | int | N |  | MUL |  | FK -> `vendor_assessment_options`.id |
| 4 | `vendor_assessment_question_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questions`.id |

---

### `vendor_assessment_options`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_question_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questions`.id |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `warning` | text | Y |  |  |  |  |
| 5 | `weight` | decimal(11,4) | N | 1.0000 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_feedbacks`.vendor_assessment_option_id, `vendor_assessment_feedbacks_vendor_assessment_options`.vendor_assessment_option_id, `vendor_assessment_option_triggers`.vendor_assessment_option_id

---

### `vendor_assessment_questionnaires`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `vendor_assessment_file_id` | int | Y |  | MUL |  | FK -> `vendor_assessment_files`.id |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |
| 7 | `deleted` | int | N | 0 |  |  |  |
| 8 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_questions`.vendor_assessment_questionnaire_id, `vendor_assessments`.vendor_assessment_questionnaire_id

---

### `vendor_assessment_questions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `vendor_assessment_questionnaire_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questionnaires`.id |
| 3 | `chapter_number` | varchar(255) | N |  |  |  |  |
| 4 | `chapter_title` | varchar(255) | N |  |  |  |  |
| 5 | `chapter_description` | text | N |  |  |  |  |
| 6 | `number` | varchar(255) | N |  |  |  |  |
| 7 | `title` | varchar(255) | N |  |  |  |  |
| 8 | `description` | text | N |  |  |  |  |
| 9 | `answer_type` | int | N |  |  |  |  |
| 10 | `score` | decimal(11,4) | N |  |  |  |  |
| 11 | `widget_type` | int | N | 0 |  |  |  |
| 12 | `hidden` | int | N | 0 |  |  |  |
| 13 | `scoring` | tinyint | N |  |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `vendor_assessment_feedbacks`.vendor_assessment_question_id, `vendor_assessment_findings_questions`.vendor_assessment_question_id, `vendor_assessment_option_triggers`.vendor_assessment_question_id, `vendor_assessment_options`.vendor_assessment_question_id

---

### `vendor_assessments`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `parent_id` | int | Y |  | MUL |  | FK -> `vendor_assessments`.id |
| 3 | `hash` | varchar(255) | N |  |  |  |  |
| 4 | `title` | varchar(255) | N |  |  |  |  |
| 5 | `description` | text | N |  |  |  |  |
| 6 | `vendor_assessment_questionnaire_id` | int | N |  | MUL |  | FK -> `vendor_assessment_questionnaires`.id |
| 7 | `portal_title` | varchar(255) | N |  |  |  |  |
| 8 | `portal_description` | text | N |  |  |  |  |
| 9 | `finding_download` | int | N |  |  |  |  |
| 10 | `questions_download` | int | N |  |  |  |  |
| 11 | `incomplete_submit` | int | N |  |  |  |  |
| 12 | `scheduling` | int | N |  |  |  |  |
| 13 | `start_date` | date | Y |  |  |  |  |
| 14 | `end_date` | date | Y |  |  |  |  |
| 15 | `auto_close` | int | N | 0 |  |  |  |
| 16 | `public_access` | int | N | 0 |  |  |  |
| 17 | `recurrence` | int | N |  |  |  |  |
| 18 | `recurrence_period` | int | N |  |  |  |  |
| 19 | `recurrence_period_type` | int | Y | 1 |  |  |  |
| 20 | `recurrence_auto_load` | int | N |  |  |  |  |
| 21 | `status` | int | N | 0 |  |  |  |
| 22 | `submited` | int | N | 0 |  |  |  |
| 23 | `submit_date` | datetime | Y |  |  |  |  |
| 24 | `review_date` | date | Y |  |  |  |  |
| 25 | `review_notes` | text | Y |  |  |  |  |
| 26 | `report_id` | int | Y |  | MUL |  | FK -> `reports`.id |
| 27 | `first_activity` | datetime | Y |  |  |  |  |
| 28 | `last_activity` | datetime | Y |  |  |  |  |
| 29 | `completed_feedbacks_percentage` | int | N | 0 |  |  |  |
| 30 | `completed_feedbacks_visible_percentage` | int | N | 0 |  |  |  |
| 31 | `uncompleted_feedbacks_percentage` | int | N | 0 |  |  |  |
| 32 | `uncompleted_feedbacks_visible_percentage` | int | N | 0 |  |  |  |
| 33 | `locked_feedbacks_percentage` | int | N | 0 |  |  |  |
| 34 | `locked_feedbacks_visible_percentage` | int | N | 0 |  |  |  |
| 35 | `unlocked_feedbacks_percentage` | int | N | 0 |  |  |  |
| 36 | `unlocked_feedbacks_visible_percentage` | int | N | 0 |  |  |  |
| 37 | `open_findings_percentage` | int | N | 0 |  |  |  |
| 38 | `expired_findings_percentage` | int | N | 0 |  |  |  |
| 39 | `total_score` | decimal(11,4) | N | 0.0000 |  |  |  |
| 40 | `max_total_score` | decimal(11,4) | N | 0.0000 |  |  |  |
| 41 | `created` | datetime | N |  |  |  |  |
| 42 | `modified` | datetime | N |  |  |  |  |
| 43 | `edited` | datetime | Y |  |  |  |  |
| 44 | `deleted` | int | N | 0 |  |  |  |
| 45 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_vendor_assessments`.vendor_assessment_id, `business_continuities_vendor_assessments`.vendor_assessment_id, `business_units_vendor_assessments`.vendor_assessment_id, `data_assets_vendor_assessments`.vendor_assessment_id, `risks_vendor_assessments`.vendor_assessment_id, `third_parties_vendor_assessments`.vendor_assessment_id, `third_party_risks_vendor_assessments`.vendor_assessment_id, `vendor_assessment_feedbacks`.vendor_assessment_id, `vendor_assessment_findings`.vendor_assessment_id, `vendor_assessments`.parent_id

---
