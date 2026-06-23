# 24. Logs & Audit Trail

Change history and operational logs: object version audit trail (audits/deltas), activity logs and system logs.

**Tables in this module:** 5  ·  **Populated:** 3  ·  Back to [index](00-index.md)

**Table list:** `activity_logs`, `archived_activity_logs`, `audit_deltas`, `audits`, `system_logs`

---

### `activity_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | Y |  |  |  | -> `users` *(inferred)* |
| 3 | `user_name` | varchar(255) | Y |  |  |  |  |
| 4 | `model` | varchar(128) | N |  | MUL |  |  |
| 5 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 6 | `parent_model` | varchar(128) | Y |  | MUL |  |  |
| 7 | `parent_foreign_key` | int | Y |  |  |  |  |
| 8 | `type` | int | Y |  |  |  |  |
| 9 | `field` | varchar(255) | Y |  |  |  |  |
| 10 | `field_label` | varchar(255) | Y |  |  |  |  |
| 11 | `old_value` | text | Y |  |  |  |  |
| 12 | `new_value` | text | Y |  |  |  |  |
| 13 | `notification_name` | varchar(255) | Y |  |  |  |  |
| 14 | `notification_type` | varchar(128) | Y |  |  |  |  |
| 15 | `notification_recipients` | text | Y |  |  |  |  |
| 16 | `dynamic_status_name` | varchar(255) | Y |  |  |  |  |
| 17 | `dynamic_status_color` | varchar(255) | Y |  |  |  |  |
| 18 | `dynamic_status_icon` | varchar(255) | Y |  |  |  |  |
| 19 | `dynamic_status_value` | varchar(128) | Y |  |  |  |  |
| 20 | `trigger_result` | text | Y |  |  |  |  |
| 21 | `subject_type` | varchar(255) | Y |  | MUL |  |  |
| 22 | `subject_id` | bigint unsigned | Y |  |  |  |  |
| 23 | `parent_id` | int | Y |  | MUL |  | FK -> `activity_logs`.id |
| 24 | `migrated` | tinyint | N | 1 |  |  |  |
| 25 | `created` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `activity_logs`.parent_id

---

### `archived_activity_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | Y |  |  |  | -> `users` *(inferred)* |
| 3 | `user_name` | varchar(255) | Y |  |  |  |  |
| 4 | `model` | varchar(128) | N |  | MUL |  |  |
| 5 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 6 | `parent_model` | varchar(128) | Y |  | MUL |  |  |
| 7 | `parent_foreign_key` | int | Y |  |  |  |  |
| 8 | `type` | int | Y |  |  |  |  |
| 9 | `field` | varchar(255) | Y |  |  |  |  |
| 10 | `field_label` | varchar(255) | Y |  |  |  |  |
| 11 | `old_value` | text | Y |  |  |  |  |
| 12 | `new_value` | text | Y |  |  |  |  |
| 13 | `notification_name` | varchar(255) | Y |  |  |  |  |
| 14 | `notification_type` | varchar(128) | Y |  |  |  |  |
| 15 | `notification_recipients` | text | Y |  |  |  |  |
| 16 | `dynamic_status_name` | varchar(255) | Y |  |  |  |  |
| 17 | `dynamic_status_color` | varchar(255) | Y |  |  |  |  |
| 18 | `dynamic_status_icon` | varchar(255) | Y |  |  |  |  |
| 19 | `dynamic_status_value` | varchar(128) | Y |  |  |  |  |
| 20 | `trigger_result` | text | Y |  |  |  |  |
| 21 | `subject_type` | varchar(255) | Y |  | MUL |  |  |
| 22 | `subject_id` | bigint unsigned | Y |  |  |  |  |
| 23 | `parent_id` | int | Y |  | MUL |  |  |
| 24 | `migrated` | tinyint | N | 1 |  |  |  |
| 25 | `created` | datetime | Y |  |  |  |  |

---

### `audit_deltas`

*Rows: 136*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | char(36) | N |  | PRI |  |  |
| 2 | `audit_id` | char(36) | N |  | MUL |  | FK -> `audits`.id |
| 3 | `property_name` | varchar(255) | N |  |  |  |  |
| 4 | `old_value` | text | Y |  |  |  |  |
| 5 | `new_value` | text | Y |  |  |  |  |

---

### `audits`

*Rows: 68*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | char(36) | N |  | PRI |  |  |
| 2 | `version` | int | N |  |  |  |  |
| 3 | `event` | varchar(255) | N |  |  |  |  |
| 4 | `event_subtype` | int | Y |  |  |  |  |
| 5 | `model` | varchar(255) | N |  |  |  |  |
| 6 | `entity_id` | varchar(36) | N |  |  |  |  |
| 7 | `request_id` | varchar(36) | N |  |  |  |  |
| 8 | `json_object` | text | N |  |  |  |  |
| 9 | `legacy` | int | N | 0 |  |  |  |
| 10 | `legacy_processed` | int | N | 0 |  |  |  |
| 11 | `legacy_object` | text | Y |  |  |  |  |
| 12 | `description` | text | Y |  |  |  |  |
| 13 | `source_id` | varchar(255) | Y |  |  |  |  |
| 14 | `restore_id` | char(36) | Y |  | MUL |  |  |
| 15 | `delta_count` | int | N | 0 |  |  |  |
| 16 | `source_ip` | varchar(255) | Y |  |  |  |  |
| 17 | `source_url` | varchar(255) | Y |  |  |  |  |
| 18 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `audit_deltas`.audit_id

---

### `system_logs`

*Rows: 5*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `sub_model` | varchar(255) | Y |  |  |  |  |
| 5 | `sub_foreign_key` | int | Y |  |  |  |  |
| 6 | `action` | int | N |  |  |  |  |
| 7 | `result` | text | Y |  |  |  |  |
| 8 | `message` | text | Y |  |  |  |  |
| 9 | `user_model` | varchar(255) | Y |  |  |  |  |
| 10 | `user_id` | int | Y |  |  |  | -> `users` *(inferred)* |
| 11 | `ip` | varchar(255) | N |  |  |  |  |
| 12 | `uri` | text | N |  |  |  |  |
| 13 | `request_id` | varchar(255) | N |  |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `edited` | datetime | Y |  |  |  |  |

---
