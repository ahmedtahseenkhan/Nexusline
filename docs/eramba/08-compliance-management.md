# 08. Compliance Management

Compliance analysis against regulations/standards: compliance packages & regulators, package items (requirements), analysis, findings, treatment strategies, statuses and online compliance audits.

**Tables in this module:** 30  ·  **Populated:** 3  ·  Back to [index](00-index.md)

**Table list:** `compliance_analysis_findings`, `compliance_analysis_findings_compliance_managements`, `compliance_analysis_findings_compliance_package_items`, `compliance_analysis_findings_compliance_package_regulators`, `compliance_audit_auditee_feedbacks`, `compliance_audit_feedback_profiles`, `compliance_audit_feedbacks`, `compliance_audit_feedbacks_compliance_audits`, `compliance_audit_overtime_graphs`, `compliance_audit_provided_feedbacks`, `compliance_audit_setting_notifications`, `compliance_audit_settings`, `compliance_audit_settings_auditees`, `compliance_audits`, `compliance_finding_classifications`, `compliance_finding_statuses`, `compliance_findings`, `compliance_findings_third_party_risks`, `compliance_managements`, `compliance_managements_projects`, `compliance_managements_risks`, `compliance_managements_security_policies`, `compliance_managements_security_services`, `compliance_managements_third_party_risks`, `compliance_package_items`, `compliance_package_regulators`, `compliance_package_regulators_legals`, `compliance_packages`, `compliance_statuses`, `compliance_treatment_strategies`

---

### `compliance_analysis_findings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `due_date` | date | Y |  |  |  |  |
| 5 | `expired` | int | N | 0 |  |  |  |
| 6 | `status` | int | N | 1 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |
| 9 | `edited` | datetime | Y |  |  |  |  |
| 10 | `deleted` | int | N | 0 |  |  |  |
| 11 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_analysis_findings_compliance_managements`.compliance_analysis_finding_id, `compliance_analysis_findings_compliance_package_items`.compliance_analysis_finding_id, `compliance_analysis_findings_compliance_package_regulators`.compliance_analysis_finding_id

---

### `compliance_analysis_findings_compliance_managements`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_analysis_finding_id` | int | N |  | MUL |  | FK -> `compliance_analysis_findings`.id |
| 3 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |

---

### `compliance_analysis_findings_compliance_package_items`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_analysis_finding_id` | int | N |  | MUL |  | FK -> `compliance_analysis_findings`.id |
| 3 | `compliance_package_item_id` | int | N |  | MUL |  | FK -> `compliance_package_items`.id |

---

### `compliance_analysis_findings_compliance_package_regulators`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_analysis_finding_id` | int | N |  | MUL |  | FK -> `compliance_analysis_findings`.id |
| 3 | `compliance_package_regulator_id` | int | N |  | MUL |  | FK -> `compliance_package_regulators`.id |

---

### `compliance_audit_auditee_feedbacks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `compliance_audit_setting_id` | int | N |  | MUL |  | FK -> `compliance_audit_settings`.id |
| 4 | `compliance_audit_feedback_profile_id` | int | N |  | MUL |  | FK -> `compliance_audit_feedback_profiles`.id |
| 5 | `compliance_audit_feedback_id` | int | N |  | MUL |  | FK -> `compliance_audit_feedbacks`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `compliance_audit_feedback_profiles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(150) | N |  |  |  |  |
| 3 | `compliance_audit_feedback_count` | int | N | 0 |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `compliance_audit_auditee_feedbacks`.compliance_audit_feedback_profile_id, `compliance_audit_feedbacks`.compliance_audit_feedback_profile_id, `compliance_audit_settings`.compliance_audit_feedback_profile_id

---

### `compliance_audit_feedbacks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_feedback_profile_id` | int | N |  | MUL |  | FK -> `compliance_audit_feedback_profiles`.id |
| 3 | `name` | varchar(150) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `compliance_audit_auditee_feedbacks`.compliance_audit_feedback_id, `compliance_audit_feedbacks_compliance_audits`.compliance_audit_feedback_id

---

### `compliance_audit_feedbacks_compliance_audits`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_feedback_id` | int | N |  | MUL |  | FK -> `compliance_audit_feedbacks`.id |
| 3 | `compliance_audit_id` | int | N |  | MUL |  | FK -> `compliance_audits`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `compliance_audit_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_id` | int | N |  | MUL |  | FK -> `compliance_audits`.id |
| 3 | `open` | int | N |  |  |  |  |
| 4 | `closed` | int | N |  |  |  |  |
| 5 | `expired` | int | N |  |  |  |  |
| 6 | `no_evidence` | int | N |  |  |  |  |
| 7 | `waiting_evidence` | int | N |  |  |  |  |
| 8 | `provided_evidence` | int | N |  |  |  |  |
| 9 | `timestamp` | varchar(45) | N |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `compliance_audit_provided_feedbacks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `compliance_audit_id` | int | N |  | MUL |  | FK -> `compliance_audits`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `compliance_audit_setting_notifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_setting_id` | int | N |  | MUL |  | FK -> `compliance_audit_settings`.id |
| 3 | `created` | datetime | N |  |  |  |  |

---

### `compliance_audit_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_id` | int | N |  | MUL |  | FK -> `compliance_audits`.id |
| 3 | `compliance_package_item_id` | int | N |  | MUL |  | FK -> `compliance_package_items`.id |
| 4 | `status` | int | Y |  |  |  |  |
| 5 | `compliance_audit_feedback_profile_id` | int | Y |  | MUL |  | FK -> `compliance_audit_feedback_profiles`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |
| 8 | `deleted` | int | N | 0 |  |  |  |
| 9 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_audit_auditee_feedbacks`.compliance_audit_setting_id, `compliance_audit_setting_notifications`.compliance_audit_setting_id, `compliance_audit_settings_auditees`.compliance_audit_setting_id

---

### `compliance_audit_settings_auditees`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_audit_setting_id` | int | N |  | MUL |  | FK -> `compliance_audit_settings`.id |
| 3 | `auditee_id` | int | N |  | MUL |  | FK -> `users`.id |

---

### `compliance_audits`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |
| 4 | `auditor_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `third_party_contact_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `start_date` | date | N |  |  |  |  |
| 7 | `end_date` | date | N |  |  |  |  |
| 8 | `auditee_title` | varchar(155) | N |  |  |  |  |
| 9 | `auditee_instructions` | text | N |  |  |  |  |
| 10 | `use_default_template` | int | N | 1 |  |  |  |
| 11 | `email_subject` | varchar(255) | N |  |  |  |  |
| 12 | `email_body` | text | N |  |  |  |  |
| 13 | `auditee_notifications` | tinyint(1) | N | 0 |  |  |  |
| 14 | `auditee_emails` | tinyint(1) | N | 0 |  |  |  |
| 15 | `auditor_notifications` | tinyint(1) | N | 0 |  |  |  |
| 16 | `auditor_emails` | tinyint(1) | N | 0 |  |  |  |
| 17 | `show_analyze_title` | tinyint(1) | N | 0 |  |  |  |
| 18 | `show_analyze_description` | tinyint(1) | N | 0 |  |  |  |
| 19 | `show_analyze_audit_criteria` | tinyint(1) | N | 0 |  |  |  |
| 20 | `show_findings` | tinyint(1) | N | 0 |  |  |  |
| 21 | `status` | varchar(50) | N | started |  |  |  |
| 22 | `compliance_finding_count` | int | N |  |  |  |  |
| 23 | `created` | datetime | N |  |  |  |  |
| 24 | `modified` | datetime | N |  |  |  |  |
| 25 | `deleted` | int | N | 0 |  |  |  |
| 26 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_audit_feedbacks_compliance_audits`.compliance_audit_id, `compliance_audit_overtime_graphs`.compliance_audit_id, `compliance_audit_provided_feedbacks`.compliance_audit_id, `compliance_audit_settings`.compliance_audit_id, `compliance_findings`.compliance_audit_id

---

### `compliance_finding_classifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_finding_id` | int | N |  | MUL |  | FK -> `compliance_findings`.id |
| 3 | `name` | varchar(150) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `compliance_finding_statuses`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(100) | N |  |  |  |  |

**Referenced by (FK):** `compliance_findings`.compliance_finding_status_id

**Configured values (2):**

| id | name |
|---|---|
| 1 | Open Item |
| 2 | Closed Item |

---

### `compliance_findings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `deadline` | date | Y |  |  |  |  |
| 5 | `expired` | int | N | 0 |  |  |  |
| 6 | `compliance_finding_status_id` | int | Y |  | MUL |  | FK -> `compliance_finding_statuses`.id |
| 7 | `compliance_audit_id` | int | N |  | MUL |  | FK -> `compliance_audits`.id |
| 8 | `compliance_package_item_id` | int | Y |  | MUL |  | FK -> `compliance_package_items`.id |
| 9 | `type` | int | N | 1 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `deleted` | int | N | 0 |  |  |  |
| 13 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_exceptions_compliance_findings`.compliance_finding_id, `compliance_finding_classifications`.compliance_finding_id, `compliance_findings_third_party_risks`.compliance_finding_id

---

### `compliance_findings_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_finding_id` | int | N |  | MUL |  | FK -> `compliance_findings`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |

---

### `compliance_managements`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_package_item_id` | int | N |  | MUL |  | FK -> `compliance_package_items`.id |
| 3 | `compliance_treatment_strategy_id` | int | Y |  | MUL |  | FK -> `compliance_treatment_strategies`.id |
| 4 | `legal_id` | int | Y |  | MUL |  | FK -> `legals`.id |
| 5 | `owner_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `efficacy` | int | Y |  |  |  |  |
| 7 | `description` | text | N |  |  |  |  |
| 8 | `workflow_owner_id` | int | Y |  |  |  |  |
| 9 | `workflow_status` | int | N | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `edited` | datetime | Y |  |  |  |  |
| 13 | `deleted` | int | N | 0 |  |  |  |
| 14 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `assets_compliance_managements`.compliance_management_id, `business_continuities_compliance_managements`.compliance_management_id, `compliance_analysis_findings_compliance_managements`.compliance_management_id, `compliance_exceptions_compliance_managements`.compliance_management_id, `compliance_managements_projects`.compliance_management_id, `compliance_managements_risks`.compliance_management_id, `compliance_managements_security_policies`.compliance_management_id, `compliance_managements_security_services`.compliance_management_id, `compliance_managements_third_party_risks`.compliance_management_id

---

### `compliance_managements_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_management_id` | int | Y |  | MUL |  | FK -> `compliance_managements`.id |
| 3 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `compliance_managements_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |
| 3 | `risk_id` | int | N |  | MUL |  | FK -> `risks`.id |

---

### `compliance_managements_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |
| 3 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |

---

### `compliance_managements_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `compliance_managements_third_party_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_management_id` | int | N |  | MUL |  | FK -> `compliance_managements`.id |
| 3 | `third_party_risk_id` | int | N |  | MUL |  | FK -> `third_party_risks`.id |

---

### `compliance_package_items`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `item_id` | varchar(255) | N |  |  |  |  |
| 3 | `name` | text | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `audit_questionaire` | text | N |  |  |  |  |
| 6 | `compliance_package_id` | int | N |  | MUL |  | FK -> `compliance_packages`.id |
| 7 | `workflow_owner_id` | int | Y |  |  |  |  |
| 8 | `workflow_status` | int | N | 0 |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |
| 11 | `deleted` | int | N | 0 |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_analysis_findings_compliance_package_items`.compliance_package_item_id, `compliance_audit_settings`.compliance_package_item_id, `compliance_findings`.compliance_package_item_id, `compliance_managements`.compliance_package_item_id

---

### `compliance_package_regulators`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `publisher_name` | varchar(255) | Y |  |  |  |  |
| 5 | `regulation_name` | varchar(255) | Y |  |  |  |  |
| 6 | `version` | varchar(128) | Y |  |  |  |  |
| 7 | `language` | varchar(128) | Y |  |  |  |  |
| 8 | `url` | text | Y |  |  |  |  |
| 9 | `restriction` | int | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `deleted` | int | N | 0 |  |  |  |
| 13 | `deleted_date` | datetime | Y |  |  |  |  |
| 14 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_analysis_findings_compliance_package_regulators`.compliance_package_regulator_id, `compliance_package_regulators_legals`.compliance_package_regulator_id, `compliance_packages`.compliance_package_regulator_id

---

### `compliance_package_regulators_legals`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `compliance_package_regulator_id` | int | N |  | MUL |  | FK -> `compliance_package_regulators`.id |
| 3 | `legal_id` | int | N |  | MUL |  | FK -> `legals`.id |

---

### `compliance_packages`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `package_id` | varchar(255) | N |  |  |  |  |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `compliance_package_regulator_id` | int | N |  | MUL |  | FK -> `compliance_package_regulators`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |
| 8 | `edited` | datetime | Y |  |  |  |  |
| 9 | `deleted` | int | N | 0 |  |  |  |
| 10 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `compliance_package_items`.compliance_package_id

---

### `compliance_statuses`

*Rows: 4*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Configured values (4):**

| id | name |
|---|---|
| 1 | On-Going |
| 2 | Compliant |
| 3 | Non-Compliant |
| 4 | Not-Applicable |

---

### `compliance_treatment_strategies`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `compliance_managements`.compliance_treatment_strategy_id

**Configured values (3):**

| id | name |
|---|---|
| 1 | Compliant |
| 2 | Not Applicable |
| 3 | Not Compliant |

---
