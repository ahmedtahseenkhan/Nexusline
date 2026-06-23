# 02. Data Assets & Privacy (GDPR / RoPA)

Information assets / Records of Processing Activities: data types, lawful bases, collection methods, retention drivers, cross-border transfers and the data-asset register.

**Tables in this module:** 18  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `data_asset_gdpr`, `data_asset_gdpr_archiving_drivers`, `data_asset_gdpr_collection_methods`, `data_asset_gdpr_data_types`, `data_asset_gdpr_lawful_bases`, `data_asset_gdpr_third_party_countries`, `data_asset_instances`, `data_asset_settings`, `data_asset_settings_third_parties`, `data_asset_settings_users`, `data_asset_statuses`, `data_assets`, `data_assets_projects`, `data_assets_risks`, `data_assets_security_policies`, `data_assets_security_services`, `data_assets_third_parties`, `data_assets_vendor_assessments`

---

### `data_asset_gdpr`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 3 | `purpose` | text | N |  |  |  |  |
| 4 | `right_to_be_informed` | text | N |  |  |  |  |
| 5 | `data_subject` | text | N |  |  |  |  |
| 6 | `volume` | text | N |  |  |  |  |
| 7 | `recived_data` | text | N |  |  |  |  |
| 8 | `contracts` | text | N |  |  |  |  |
| 9 | `retention` | text | N |  |  |  |  |
| 10 | `encryption` | text | N |  |  |  |  |
| 11 | `right_to_erasure` | text | N |  |  |  |  |
| 12 | `archiving_driver_empty` | int | N | 0 |  |  |  |
| 13 | `origin` | text | N |  |  |  |  |
| 14 | `destination` | text | N |  |  |  |  |
| 15 | `transfer_outside_eea` | int | N | 0 |  |  |  |
| 16 | `third_party_involved_all` | int | N | 0 |  |  |  |
| 17 | `security` | text | N |  |  |  |  |
| 18 | `right_to_portability` | text | N |  |  |  |  |
| 19 | `stakeholders` | text | N |  |  |  |  |
| 20 | `accuracy` | text | N |  |  |  |  |
| 21 | `right_to_access` | text | N |  |  |  |  |
| 22 | `right_to_rectification` | text | N |  |  |  |  |
| 23 | `right_to_decision` | text | N |  |  |  |  |
| 24 | `right_to_object` | text | N |  |  |  |  |
| 25 | `created` | datetime | N |  |  |  |  |
| 26 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `data_asset_gdpr_archiving_drivers`.data_asset_gdpr_id, `data_asset_gdpr_collection_methods`.data_asset_gdpr_id, `data_asset_gdpr_data_types`.data_asset_gdpr_id, `data_asset_gdpr_lawful_bases`.data_asset_gdpr_id, `data_asset_gdpr_third_party_countries`.data_asset_gdpr_id

---

### `data_asset_gdpr_archiving_drivers`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_gdpr_id` | int | N |  | MUL |  | FK -> `data_asset_gdpr`.id |
| 3 | `archiving_driver` | int | N |  |  |  |  |

---

### `data_asset_gdpr_collection_methods`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_gdpr_id` | int | N |  | MUL |  | FK -> `data_asset_gdpr`.id |
| 3 | `collection_method` | int | N |  |  |  |  |

---

### `data_asset_gdpr_data_types`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_gdpr_id` | int | N |  | MUL |  | FK -> `data_asset_gdpr`.id |
| 3 | `data_type` | int | N |  |  |  |  |

---

### `data_asset_gdpr_lawful_bases`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_gdpr_id` | int | N |  | MUL |  | FK -> `data_asset_gdpr`.id |
| 3 | `lawful_base` | int | N |  |  |  |  |

---

### `data_asset_gdpr_third_party_countries`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_gdpr_id` | int | N |  | MUL |  | FK -> `data_asset_gdpr`.id |
| 3 | `third_party_country` | int | N |  |  |  |  |

---

### `data_asset_instances`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |
| 3 | `analysis_unlocked` | int | N | 0 |  |  |  |
| 4 | `asset_missing_review` | int | N | 0 |  |  |  |
| 5 | `controls_with_issues` | int | N | 0 |  |  |  |
| 6 | `controls_with_failed_audits` | int | N | 0 |  |  |  |
| 7 | `controls_with_missing_audits` | int | N | 0 |  |  |  |
| 8 | `policies_with_missing_reviews` | int | N | 0 |  |  |  |
| 9 | `risks_with_missing_reviews` | int | N | 0 |  |  |  |
| 10 | `project_expired` | int | N | 0 |  |  |  |
| 11 | `expired_tasks` | int | N | 0 |  |  |  |
| 12 | `incomplete_analysis` | int | N | 0 |  |  |  |
| 13 | `incomplete_gdpr_analysis` | int | N | 0 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `data_asset_settings`.data_asset_instance_id, `data_assets`.data_asset_instance_id

---

### `data_asset_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `data_asset_instance_id` | int | N |  | MUL |  | FK -> `data_asset_instances`.id |
| 4 | `gdpr_enabled` | int | N |  |  |  |  |
| 5 | `driver_for_compliance` | text | N |  |  |  |  |
| 6 | `dpo_empty` | int | N | 0 |  |  |  |
| 7 | `processor_empty` | int | N | 0 |  |  |  |
| 8 | `controller_empty` | int | N | 0 |  |  |  |
| 9 | `controller_representative_empty` | int | Y | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `data_asset_settings_third_parties`.data_asset_setting_id, `data_asset_settings_users`.data_asset_setting_id

---

### `data_asset_settings_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | varchar(50) | N |  |  |  |  |
| 3 | `data_asset_setting_id` | int | N |  | MUL |  | FK -> `data_asset_settings`.id |
| 4 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `data_asset_settings_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | varchar(50) | N |  |  |  |  |
| 3 | `data_asset_setting_id` | int | N |  | MUL |  | FK -> `data_asset_settings`.id |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |

---

### `data_asset_statuses`

*Rows: 7*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `data_assets`.data_asset_status_id

**Configured values (7):**

| id | name |
|---|---|
| 1 | Created |
| 2 | Modified |
| 3 | Stored |
| 4 | Transit |
| 5 | Deleted |
| 6 | Tainted / Broken |
| 7 | Unnecessary |

---

### `data_assets`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `data_asset_instance_id` | int | N |  | MUL |  | FK -> `data_asset_instances`.id |
| 5 | `order` | int | N | 0 | MUL |  |  |
| 6 | `data_asset_status_id` | int | Y |  | MUL |  | FK -> `data_asset_statuses`.id |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |
| 9 | `edited` | datetime | Y |  |  |  |  |
| 10 | `deleted` | int | N | 0 |  |  |  |
| 11 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `data_asset_gdpr`.data_asset_id, `data_assets_projects`.data_asset_id, `data_assets_risks`.data_asset_id, `data_assets_security_policies`.data_asset_id, `data_assets_security_services`.data_asset_id, `data_assets_third_parties`.data_asset_id, `data_assets_vendor_assessments`.data_asset_id

---

### `data_assets_projects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `project_id` | int | Y |  | MUL |  | FK -> `projects`.id |
| 3 | `data_asset_id` | int | Y |  | MUL |  | FK -> `data_assets`.id |

---

### `data_assets_risks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(20) | N | 0 |  |  |  |
| 3 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 4 | `risk_id` | int | N |  | MUL |  | -> `risks` *(inferred)* |

---

### `data_assets_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 3 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |

---

### `data_assets_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `data_assets_third_parties`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 3 | `third_party_id` | int | N |  | MUL |  | FK -> `third_parties`.id |

---

### `data_assets_vendor_assessments`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data_asset_id` | int | N |  | MUL |  | FK -> `data_assets`.id |
| 3 | `vendor_assessment_id` | int | N |  | MUL |  | FK -> `vendor_assessments`.id |

---
