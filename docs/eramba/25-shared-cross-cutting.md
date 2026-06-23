# 25. Shared & Cross-Cutting Objects

Objects attached to many module types: comments, attachments, tags, periodic reviews, issues/findings, system records, concurrent-edit locks and trash.

**Tables in this module:** 9  ·  **Populated:** 2  ·  Back to [index](00-index.md)

**Table list:** `attachments`, `comments`, `concurrent_edits`, `issues`, `review_setting_custom_roles`, `review_settings`, `reviews`, `system_records`, `tags`

---

### `attachments`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 1 |  |  |  |
| 3 | `hash` | varchar(255) | N |  |  |  |  |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 6 | `activity_log_id` | int | Y |  |  |  | -> `activity_logs` *(inferred)* |
| 7 | `name` | text | Y |  |  |  |  |
| 8 | `filename` | text | N |  |  |  |  |
| 9 | `extension` | varchar(155) | N |  |  |  |  |
| 10 | `mime_type` | varchar(155) | N |  |  |  |  |
| 11 | `file_size` | int | N |  |  |  |  |
| 12 | `description` | text | N |  |  |  |  |
| 13 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 14 | `comment_id` | int unsigned | Y |  | MUL |  | -> `comments` *(inferred)* |
| 15 | `user_name` | varchar(255) | Y |  |  |  |  |
| 16 | `latest` | int | N | 0 |  |  |  |
| 17 | `created` | datetime | N |  |  |  |  |
| 18 | `modified` | datetime | N |  |  |  |  |

---

### `comments`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 0 |  |  |  |
| 3 | `hash` | varchar(255) | N |  |  |  |  |
| 4 | `model` | varchar(150) | N |  |  |  |  |
| 5 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 6 | `activity_log_id` | int | Y |  |  |  | -> `activity_logs` *(inferred)* |
| 7 | `message` | text | N |  |  |  |  |
| 8 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 9 | `user_name` | varchar(255) | Y |  |  |  |  |
| 10 | `latest` | int | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |

---

### `concurrent_edits`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `expires` | datetime | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `issues`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(150) | N |  |  |  |  |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `date_start` | date | N |  |  |  |  |
| 5 | `date_end` | date | Y |  |  |  |  |
| 6 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 7 | `description` | text | N |  |  |  |  |
| 8 | `status` | varchar(255) | N | open |  |  |  |
| 9 | `workflow_owner_id` | int | Y |  |  |  |  |
| 10 | `workflow_status` | int | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |
| 13 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `security_service_issues_security_services`.security_service_issue_id

---

### `review_setting_custom_roles`

*Rows: 5*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `review_setting_id` | int | N |  | MUL |  | FK -> `review_settings`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `review_settings`

*Rows: 5*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(128) | Y |  |  |  |  |
| 3 | `created` | datetime | Y |  |  |  |  |
| 4 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `review_setting_custom_roles`.review_setting_id

---

### `reviews`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(150) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `planned_date` | date | Y |  |  |  |  |
| 5 | `actual_date` | date | Y |  |  |  |  |
| 6 | `user_id` | int | Y |  | MUL |  | -> `users` *(inferred)* |
| 7 | `description` | text | N |  |  |  |  |
| 8 | `completed` | int | N | 0 |  |  |  |
| 9 | `use_attachments` | int | Y |  |  |  |  |
| 10 | `policy_description` | text | Y |  |  |  |  |
| 11 | `url` | text | Y |  |  |  |  |
| 12 | `version` | varchar(150) | Y |  |  |  |  |
| 13 | `reviewers_log` | text | Y |  |  |  |  |
| 14 | `completed_by_user` | text | Y |  |  |  |  |
| 15 | `workflow_owner_id` | int | Y |  |  |  |  |
| 16 | `workflow_status` | int | N | 0 |  |  |  |
| 17 | `created` | datetime | N |  |  |  |  |
| 18 | `modified` | datetime | N |  |  |  |  |
| 19 | `edited` | datetime | Y |  |  |  |  |
| 20 | `deleted` | int | N | 0 |  |  |  |
| 21 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `system_records`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(70) | N |  |  |  |  |
| 3 | `model_nice` | varchar(70) | N |  |  |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `item` | varchar(100) | N |  |  |  |  |
| 6 | `notes` | text | Y |  |  |  |  |
| 7 | `type` | int | N |  |  |  |  |
| 8 | `workflow_status` | int | Y |  |  |  |  |
| 9 | `workflow_comment` | text | Y |  |  |  |  |
| 10 | `ip` | varchar(45) | N |  |  |  |  |
| 11 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 12 | `created` | datetime | N |  |  |  |  |

---

### `tags`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(250) | N |  |  |  |  |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `title` | varchar(150) | N |  |  |  |  |
| 5 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `created` | datetime | N |  |  |  |  |

---
