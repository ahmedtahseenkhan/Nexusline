# 16. Users, Roles & Access Control

Identity & authorization: user accounts, groups, portals, team roles, ACL (ARO/ACO), permission grants and custom roles.

**Tables in this module:** 26  ·  **Populated:** 13  ·  Back to [index](00-index.md)

**Table list:** `acos`, `aros`, `aros_acos`, `authorization_custom_group_permissions`, `authorization_custom_user_permissions`, `authorization_group_permissions`, `authorization_user_permissions`, `authorizations`, `custom_roles_groups`, `custom_roles_role_groups`, `custom_roles_role_users`, `custom_roles_roles`, `custom_roles_users`, `groups`, `login_attempts`, `login_bans`, `portals`, `scopes`, `sections`, `stats_logins`, `team_roles`, `user_account_requirements`, `users`, `users_groups`, `users_ldap_synchronizations`, `users_portals`

---

### `acos`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `parent_id` | int | Y |  |  |  |  |
| 3 | `model` | varchar(255) | Y |  | MUL |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 5 | `alias` | varchar(255) | Y |  | MUL |  |  |
| 6 | `lft` | int | Y |  |  |  |  |
| 7 | `rght` | int | Y |  |  |  |  |

---

### `aros`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `parent_id` | int | Y |  |  |  |  |
| 3 | `model` | varchar(255) | Y |  | MUL |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 5 | `alias` | varchar(255) | Y |  | MUL |  |  |
| 6 | `lft` | int | Y |  |  |  |  |
| 7 | `rght` | int | Y |  |  |  |  |

---

### `aros_acos`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `aro_id` | int | N |  | MUL |  | -> `aros` *(inferred)* |
| 3 | `aco_id` | int | N |  |  |  | -> `acos` *(inferred)* |
| 4 | `_create` | varchar(2) | N | 0 |  |  |  |
| 5 | `_read` | varchar(2) | N | 0 |  |  |  |
| 6 | `_update` | varchar(2) | N | 0 |  |  |  |
| 7 | `_delete` | varchar(2) | N | 0 |  |  |  |

**Referenced by (FK):** `visualisation_settings_groups`.aros_acos_id, `visualisation_settings_users`.aros_acos_id, `visualisation_share_groups`.aros_acos_id, `visualisation_share_users`.aros_acos_id

---

### `authorization_custom_group_permissions`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `authorization_id` | int | N |  | MUL |  | FK -> `authorizations`.id |
| 3 | `group_id` | int | N |  | MUL |  | FK -> `custom_roles_groups`.id |
| 4 | `action` | varchar(128) | N |  | MUL |  |  |
| 5 | `permission` | int | N | 0 |  |  |  |

---

### `authorization_custom_user_permissions`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `authorization_id` | int | N |  | MUL |  | FK -> `authorizations`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `custom_roles_users`.id |
| 4 | `action` | varchar(128) | N |  | MUL |  |  |
| 5 | `permission` | int | N | 0 |  |  |  |

---

### `authorization_group_permissions`

*Rows: 1296 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `authorization_id` | int | N |  | MUL |  | FK -> `authorizations`.id |
| 3 | `group_id` | int | N |  | MUL |  | FK -> `groups`.id |
| 4 | `action` | varchar(128) | N |  |  |  |  |
| 5 | `permission` | int | N | 0 |  |  |  |

---

### `authorization_user_permissions`

*Rows: 61 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `authorization_id` | int | N |  | MUL |  | FK -> `authorizations`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `action` | varchar(128) | N |  | MUL |  |  |
| 5 | `permission` | int | N | 0 |  |  |  |

---

### `authorizations`

*Rows: 1002 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `parent_id` | int | Y |  | MUL |  | FK -> `authorizations`.id |
| 3 | `model` | varchar(255) | N |  | MUL |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |

**Referenced by (FK):** `authorization_custom_group_permissions`.authorization_id, `authorization_custom_user_permissions`.authorization_id, `authorization_group_permissions`.authorization_id, `authorization_user_permissions`.authorization_id, `authorizations`.parent_id

---

### `custom_roles_groups`

*Rows: 14*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `group_id` | int | N | 0 | MUL |  | FK -> `groups`.id |
| 3 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `authorization_custom_group_permissions`.group_id

---

### `custom_roles_role_groups`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `custom_roles_role_id` | int | N |  | MUL |  | FK -> `custom_roles_roles`.id |
| 5 | `group_id` | int | Y |  | MUL |  | FK -> `groups`.id |
| 6 | `created` | datetime | Y |  |  |  |  |

---

### `custom_roles_role_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `custom_roles_role_id` | int | N |  | MUL |  | FK -> `custom_roles_roles`.id |
| 5 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `created` | datetime | Y |  |  |  |  |

---

### `custom_roles_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | Y |  | MUL |  |  |
| 3 | `field` | varchar(155) | N |  |  |  |  |

**Referenced by (FK):** `custom_roles_role_groups`.custom_roles_role_id, `custom_roles_role_users`.custom_roles_role_id

---

### `custom_roles_users`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `authorization_custom_user_permissions`.user_id

---

### `groups`

*Rows: 14*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | MUL |  |  |
| 3 | `description` | text | Y |  |  |  |  |
| 4 | `status` | int | Y | 1 |  |  |  |
| 5 | `slug` | varchar(255) | Y |  | UNI |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |
| 8 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `authorization_group_permissions`.group_id, `awareness_programs_groups`.group_id, `custom_roles_groups`.group_id, `custom_roles_role_groups`.group_id, `ldap_synchronizations_groups`.group_id, `user_fields_groups`.group_id

**Configured values (14):**

| id | name | description | status | slug | created | modified | edited |
|---|---|---|---|---|---|---|---|
| 10 | Admin | This is a system message, this group might not have updated ACLs please make sure you edit and review them | 1 | ADMIN | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 11 | Third Party Feedback | This is a system message, this group might not have updated ACLs please make sure you edit and review them | 1 | THIRD_PARTY_FEEDBACK | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 12 | Notification Feedback | This is a system message, this group might not have updated ACLs please make sure you edit and review them | 1 | NOTIFICATION_FEEDBACK | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 13 | All but Settings | This is a system message, this group might not have updated ACLs please make sure you edit and review them | 1 | ALL_BUT_SETTINGS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 14 | System Group - View Policies and Reviews | This group only allows users to see policies and their reviews under the policy management module.\nDisclaimer: always review the group permissions before assigning them to users, they might grant access you do not want or be outdated as releases move forward. | 1 | VIEW_POLICIES_AND_REVIEWS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 15 | System Group - View Item Reports | This group allows users to visualise item reports from any section that they have access (granted by another group). Disclaimer: always review the group permissions before assigning them to users, they might grant access you do not want or be outdated as releases move forward. | 1 | VIEW_ITEM_REPORTS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 16 | System Group - View Internal Controls and Audits, Maintenances and Issues | This group grants permissions to only view internal controls and their related items. Disclaimer: always review the group permissions before assigning them to users, they might grant access you do not want or be outdated as releases move forward. | 1 | VIEW_INT_CTRL_AND_AMI | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 17 | System Group - View All Types of Risks and their Reviews | This group grants access to view all three types of risks and their respective reviews. Disclaimer: always review the group permissions before assigning them to users, they might grant access you do not want or be outdated as releases move forward. | 1 | VIEW_RISKS_AND_REVIEWS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 18 | System Group - Projects and Tasks | This group grants access to view projects and tasks. Disclaimer: always review the group permissions before assigning them to users, they might grant access you do not want or be outdated as releases move forward. | 1 | PROJECTS_AND_TASKS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 19 | User Management | This group allows members to add, edit, import and delete user accounts. Add this group to System / Settings / User Management if you want them to be able to edit and delete accounts other than theirs. | 1 | USER_MANAGEMENT | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 20 | Comments and Attachments | This group allows members to view, add comments and to view, add, download attachments. | 1 | COMMENTS_ATTACHMENTS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 21 | System Group - View All Exceptions | This groups allows users to see the index page of all three exception modules. | 1 | VIEW_ALL_EXCEPTIONS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 22 | System Group - View All Assets and their Reviews | This groups allows users to see the index page of all three exception modules. | 1 | VIEW_ASSETS_AND_REVIEWS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |
| 23 | No Allowed Permissions | This group has no access to eramba main functionalities and is typically used when creating accounts that will only use the Online Assessment or Account review portals. | 1 | NO_ALLOWED_PERMISSIONS | 2026-06-18 22:08:35 | 2026-06-18 22:08:35 |  |

---

### `login_attempts`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `login` | varchar(255) | N |  |  |  |  |
| 3 | `portal_id` | int | Y |  | MUL |  | FK -> `portals`.id |
| 4 | `type` | int | N |  |  |  |  |
| 5 | `result` | int | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `login_bans`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `login` | varchar(255) | N |  |  |  |  |
| 3 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `until` | datetime | N |  |  |  |  |
| 5 | `canceled` | datetime | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `portals`

*Rows: 5*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |

**Referenced by (FK):** `ldap_synchronizations_portals`.portal_id, `login_attempts`.portal_id, `users_portals`.portal_id

**Configured values (5):**

| id | name |
|---|---|
| 1 | main |
| 2 | vendor_assessments |
| 3 | account_reviews |
| 4 | awareness |
| 5 | policy |

---

### `scopes`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `ciso_role_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 3 | `ciso_deputy_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `board_representative_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 5 | `board_representative_deputy_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `sections`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |

---

### `stats_logins`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `created` | datetime | Y |  |  |  |  |

---

### `team_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 3 | `role` | varchar(255) | N |  |  |  |  |
| 4 | `responsibilities` | text | N |  |  |  |  |
| 5 | `competences` | text | N |  |  |  |  |
| 6 | `status` | varchar(255) | Y |  |  |  |  |
| 7 | `workflow_owner_id` | int | Y |  |  |  |  |
| 8 | `workflow_status` | int | N | 0 |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |
| 11 | `edited` | datetime | Y |  |  |  |  |
| 12 | `deleted` | int | N | 0 |  |  |  |
| 13 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `user_account_requirements`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `step` | varchar(128) | N |  |  |  |  |
| 4 | `completed` | int | Y | 0 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `users`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `surname` | varchar(255) | Y |  |  |  |  |
| 4 | `email` | varchar(255) | N |  | UNI |  |  |
| 5 | `login` | varchar(255) | N |  | UNI |  |  |
| 6 | `password` | varchar(255) | N |  |  |  |  |
| 7 | `language` | varchar(10) | Y |  |  |  |  |
| 8 | `status` | int | N | 1 |  |  |  |
| 9 | `blocked` | int | N | 0 |  |  |  |
| 10 | `local_account` | int | Y | 1 |  |  |  |
| 11 | `api_allow` | int | N | 0 |  |  |  |
| 12 | `default_password` | int | N | 1 |  |  |  |
| 13 | `account_ready` | int | N | 0 |  |  |  |
| 14 | `ldap_sync` | int | N | 0 |  |  |  |
| 15 | `ldap_synchronization_id` | int | Y |  | MUL |  | -> `ldap_synchronizations` *(inferred)* |
| 16 | `created` | datetime | N |  |  |  |  |
| 17 | `modified` | datetime | N |  |  |  |  |
| 18 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feedbacks`.user_id, `advanced_filter_user_params`.user_id, `advanced_filter_user_settings`.user_id, `advanced_filters`.user_id, `app_notification_views`.user_id, `app_notifications`.user_id, `attachments`.user_id, `authorization_user_permissions`.user_id, `awareness_program_active_users`.user_id, `awareness_program_compliant_users`.user_id, `awareness_program_missed_recurrences`.user_id, `awareness_program_not_compliant_users`.user_id, `awareness_program_recurrence_reminders`.user_id, `awareness_program_recurrence_trainings`.user_id, `bulk_actions`.user_id, `business_continuity_plan_audit_improvements`.user_id, `business_continuity_plan_audits`.user_id, `comments`.user_id, `compliance_audit_auditee_feedbacks`.user_id, `compliance_audit_provided_feedbacks`.user_id, `compliance_audit_settings_auditees`.auditee_id, `compliance_audits`.auditor_id, `compliance_audits`.third_party_contact_id, `compliance_managements`.owner_id, `concurrent_edits`.user_id, `custom_roles_role_users`.user_id, `custom_roles_users`.user_id, `data_asset_settings_users`.user_id, `filter_user_settings`.user_id, `filters`.user_id, `goal_audits`.user_id, `goals`.owner_id, `issues`.user_id, `login_bans`.user_id, `mcp_daily_prompt_usage_counters`.user_id, `mcp_daily_usage_counters`.user_id, `notification_system_item_custom_users`.user_id, `notification_system_item_feedbacks`.user_id, `notification_system_items_users`.user_id, `notifications`.user_id, `oauth2_access_tokens`.user_id, `oauth2_authorization_codes`.user_id, `oauth2_refresh_tokens`.user_id, `scopes`.board_representative_deputy_id, `scopes`.board_representative_id, `scopes`.ciso_deputy_id, `scopes`.ciso_role_id, `security_policy_reviews`.reviewer_id, `system_records`.user_id, `tags`.user_id, `team_roles`.user_id, `tooltip_logs`.user_id, `user_account_requirements`.user_id, `user_fields_users`.user_id, `user_tokens`.user_id, `users_ldap_synchronizations`.user_id, `users_portals`.user_id, `vendor_assessment_feedbacks`.user_id, `widget_views`.user_id, `workflow_acknowledgements`.user_id, `workflow_logs`.user_id, `workflows_all_approver_items`.user_id, `workflows_all_validator_items`.user_id, `workflows_approver_scopes`.user_id, `workflows_approvers`.user_id, `workflows_validator_scopes`.user_id, `workflows_validators`.user_id

---

### `users_groups`

*Rows: 1 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  |  |  | -> `users` *(inferred)* |
| 3 | `group_id` | int | N |  |  |  | -> `groups` *(inferred)* |

---

### `users_ldap_synchronizations`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `ldap_synchronization_id` | int | N |  | MUL |  | FK -> `ldap_synchronizations`.id |

---

### `users_portals`

*Rows: 3 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `portal_id` | int | N |  | MUL |  | FK -> `portals`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---
