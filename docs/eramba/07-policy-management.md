# 07. Policy Management

Security policy documents: lifecycle, document types, reviews, related policies/controls, portal publication and per-policy roles.

**Tables in this module:** 9  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `log_security_policies`, `policy_users`, `security_policies`, `security_policies_related`, `security_policies_security_services`, `security_policy_custom_roles`, `security_policy_document_types`, `security_policy_ldap_groups`, `security_policy_reviews`

---

### `log_security_policies`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  |  |  | -> `security_policies` *(inferred)* |
| 3 | `index` | varchar(255) | N |  |  |  |  |
| 4 | `short_description` | varchar(150) | N |  |  |  |  |
| 5 | `description` | text | Y |  |  |  |  |
| 6 | `document_type` | varchar(255) | N |  |  |  |  |
| 7 | `version` | varchar(50) | N |  |  |  |  |
| 8 | `published_date` | date | N |  |  |  |  |
| 9 | `next_review_date` | date | N |  |  |  |  |
| 10 | `permission` | varchar(255) | N |  |  |  |  |
| 11 | `ldap_connector_id` | int | Y |  |  |  | -> `ldap_connectors` *(inferred)* |
| 12 | `asset_label_id` | int | Y |  |  |  | -> `asset_labels` *(inferred)* |
| 13 | `user_edit_id` | int | Y |  |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |

---

### `policy_users`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `login` | varchar(45) | N |  |  |  |  |
| 3 | `created` | datetime | N |  |  |  |  |

---

### `security_policies`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `index` | varchar(255) | N |  | MUL |  |  |
| 3 | `short_description` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | Y |  |  |  |  |
| 5 | `url` | text | Y |  |  |  |  |
| 6 | `use_attachments` | int | N | 0 |  |  |  |
| 7 | `document_type` | varchar(255) | N |  |  |  |  |
| 8 | `security_policy_document_type_id` | int | Y |  | MUL |  | FK -> `security_policy_document_types`.id |
| 9 | `version` | varchar(50) | N |  |  |  |  |
| 10 | `published_date` | date | N |  |  |  |  |
| 11 | `next_review_date` | date | N |  |  |  |  |
| 12 | `permission` | varchar(255) | N |  |  |  |  |
| 13 | `ldap_connector_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 14 | `ldap_groups_required` | int | N | 0 |  |  |  |
| 15 | `asset_label_id` | int | Y |  | MUL |  | FK -> `asset_labels`.id |
| 16 | `status` | int | N | 0 |  |  |  |
| 17 | `expired_reviews` | int | N | 0 |  |  |  |
| 18 | `hash` | varchar(255) | Y |  |  |  |  |
| 19 | `workflow_owner_id` | int | Y |  |  |  |  |
| 20 | `workflow_status` | int | N | 0 |  |  |  |
| 21 | `created` | datetime | N |  |  |  |  |
| 22 | `modified` | datetime | N |  |  |  |  |
| 23 | `edited` | datetime | Y |  |  |  |  |
| 24 | `deleted` | int | N | 0 |  |  |  |
| 25 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `awareness_programs_security_policies`.security_policy_id, `compliance_managements_security_policies`.security_policy_id, `data_assets_security_policies`.security_policy_id, `goals_security_policies`.security_policy_id, `policy_exceptions_security_policies`.security_policy_id, `projects_security_policies`.security_policy_id, `risks_security_policies`.security_policy_id, `security_policies_related`.related_document_id, `security_policies_related`.security_policy_id, `security_policies_security_services`.security_policy_id, `security_policy_custom_roles`.security_policy_id, `security_policy_ldap_groups`.security_policy_id, `security_policy_reviews`.security_policy_id

---

### `security_policies_related`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `related_document_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `security_policies_security_services`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `security_service_id` | int | N |  | MUL |  | FK -> `security_services`.id |

---

### `security_policy_custom_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `security_policy_document_types`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `editable` | int | N | 1 |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `security_policies`.security_policy_document_type_id

**Configured values (3):**

| id | name | editable | created | modified |
|---|---|---|---|---|
| 1 | Procedure | 0 | 2022-01-01 12:34:56 | 2022-01-01 12:34:56 |
| 2 | Standard | 0 | 2022-01-01 12:34:56 | 2022-01-01 12:34:56 |
| 3 | Policy | 0 | 2022-01-01 12:34:56 | 2022-01-01 12:34:56 |

---

### `security_policy_ldap_groups`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `security_policy_reviews`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `planned_date` | date | N |  |  |  |  |
| 4 | `actual_review_date` | date | Y |  |  |  |  |
| 5 | `reviewer_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `comments` | text | N |  |  |  |  |
| 7 | `workflow_status` | int | N | 0 |  |  |  |
| 8 | `workflow_owner_id` | int | Y |  |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |

---
