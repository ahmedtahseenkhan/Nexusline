# 23. System Administration

Operational plumbing: backups, CRON scheduler, async queue/jobs, imports, bulk actions, software updates, licensing and sessions.

**Tables in this module:** 22  ·  **Populated:** 9  ·  Back to [index](00-index.md)

**Table list:** `backups`, `bulk_action_objects`, `bulk_actions`, `cake_sessions`, `cron`, `cron_dynamic_queue`, `cron_tasks`, `data_migrations_phinxlog`, `diagnostic_incidents`, `imports`, `integrity_check_findings`, `license_checks`, `mcp_daily_prompt_usage_counters`, `mcp_daily_usage_counters`, `phinxlog`, `queue`, `queue_processes`, `queued_jobs`, `schema_migrations`, `sessions`, `updates`, `v3_upgrade_pending_changes`

---

### `backups`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `sql_file` | varchar(255) | N |  |  |  |  |
| 3 | `name` | text | N |  |  |  |  |
| 4 | `filename` | text | N |  |  |  |  |
| 5 | `type` | int | N | 1 |  |  |  |
| 6 | `origin` | int | N | 1 |  |  |  |
| 7 | `instance` | varchar(255) | Y |  |  |  |  |
| 8 | `part` | int | Y |  |  |  |  |
| 9 | `parts_total` | int | Y |  |  |  |  |
| 10 | `fetched` | datetime | Y |  |  |  |  |
| 11 | `completed` | datetime | Y |  |  |  |  |
| 12 | `failed` | int | N | 0 |  |  |  |
| 13 | `failure_message` | text | Y |  |  |  |  |
| 14 | `deleted_files` | int | N | 0 |  |  |  |
| 15 | `created` | datetime | N |  |  |  |  |

---

### `bulk_action_objects`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `bulk_action_id` | int | N |  | MUL |  | FK -> `bulk_actions`.id |
| 3 | `model` | varchar(150) | N |  |  |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |

---

### `bulk_actions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N |  |  |  |  |
| 3 | `model` | varchar(150) | N |  |  |  |  |
| 4 | `json_data` | text | N |  |  |  |  |
| 5 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `bulk_action_objects`.bulk_action_id

---

### `cake_sessions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | varchar(255) | N |  | PRI |  |  |
| 2 | `data` | text | Y |  |  |  |  |
| 3 | `expires` | int | Y |  |  |  |  |

---

### `cron`

*Rows: 19*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | varchar(128) | N |  |  |  |  |
| 3 | `execution_time` | float | Y |  |  |  |  |
| 4 | `status` | varchar(128) | Y | success |  |  |  |
| 5 | `request_id` | varchar(36) | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `completed` | datetime | Y |  |  |  |  |
| 8 | `url` | varchar(255) | Y |  |  |  |  |
| 9 | `message` | text | Y |  |  |  |  |

**Referenced by (FK):** `advanced_filter_crons`.cron_id, `cron_tasks`.cron_id

---

### `cron_dynamic_queue`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | Y |  |  |  |  |
| 3 | `status` | int | N | 0 |  |  |  |
| 4 | `created` | datetime | Y |  |  |  |  |
| 5 | `modified` | datetime | Y |  |  |  |  |

---

### `cron_tasks`

*Rows: 154*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `cron_id` | int | N |  | MUL |  | FK -> `cron`.id |
| 3 | `task` | varchar(128) | N |  |  |  |  |
| 4 | `status` | int | N | 0 |  |  |  |
| 5 | `execution_time` | float | Y |  |  |  |  |
| 6 | `message` | text | Y |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `completed` | datetime | Y |  |  |  |  |

---

### `data_migrations_phinxlog`

*Rows: 91*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `version` | bigint | N |  | PRI |  |  |
| 2 | `migration_name` | varchar(100) | Y |  |  |  |  |
| 3 | `start_time` | timestamp | Y |  |  |  |  |
| 4 | `end_time` | timestamp | Y |  |  |  |  |
| 5 | `breakpoint` | tinyint(1) | N | 0 |  |  |  |

---

### `diagnostic_incidents`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `exception` | varchar(255) | N |  |  |  |  |
| 3 | `code` | int | Y |  |  |  |  |
| 4 | `file` | varchar(255) | Y |  |  |  |  |
| 5 | `file_app` | varchar(255) | Y |  |  |  |  |
| 6 | `line` | int | Y |  |  |  |  |
| 7 | `message` | text | Y |  |  |  |  |
| 8 | `archive` | varchar(255) | N |  |  |  |  |
| 9 | `send_status` | int | N |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |

---

### `imports`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(256) | Y |  |  |  |  |
| 3 | `file` | varchar(256) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `integrity_check_findings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | Y |  | MUL |  |  |
| 3 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 4 | `message` | text | Y |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `license_checks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `result` | tinyint(1) | N |  |  |  |  |
| 3 | `end_date` | date | Y |  |  |  |  |
| 4 | `owner` | varchar(255) | Y |  |  |  |  |
| 5 | `message` | varchar(255) | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `mcp_daily_prompt_usage_counters`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `usage_date` | date | N |  | MUL |  |  |
| 4 | `prompt_count` | int unsigned | N | 0 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

---

### `mcp_daily_usage_counters`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `usage_date` | date | N |  | MUL |  |  |
| 4 | `tool_call_count` | int unsigned | N | 0 |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | Y |  |  |  |  |

---

### `phinxlog`

*Rows: 127*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `version` | bigint | N |  | PRI |  |  |
| 2 | `migration_name` | varchar(100) | Y |  |  |  |  |
| 3 | `start_time` | timestamp | Y |  |  |  |  |
| 4 | `end_time` | timestamp | Y |  |  |  |  |
| 5 | `breakpoint` | tinyint(1) | N | 0 |  |  |  |

---

### `queue`

*Rows: 3*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `data` | mediumtext | Y |  |  |  |  |
| 3 | `queue_id` | varchar(255) | Y |  |  |  |  |
| 4 | `model` | varchar(128) | Y |  |  |  |  |
| 5 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 6 | `description` | text | Y |  |  |  |  |
| 7 | `status` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

---

### `queue_processes`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `pid` | varchar(40) | N |  | MUL |  |  |
| 3 | `created` | datetime | N |  |  |  |  |
| 4 | `modified` | datetime | N |  |  |  |  |
| 5 | `terminate` | tinyint(1) | N | 0 |  |  |  |
| 6 | `server` | varchar(90) | Y |  |  |  |  |
| 7 | `workerkey` | varchar(45) | N |  | UNI |  |  |

---

### `queued_jobs`

*Rows: 211*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `job_task` | varchar(90) | N |  | MUL |  |  |
| 3 | `data` | text | Y |  |  |  |  |
| 4 | `job_group` | varchar(255) | Y |  |  |  |  |
| 5 | `reference` | varchar(255) | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `notbefore` | datetime | Y |  |  |  |  |
| 8 | `fetched` | datetime | Y |  |  |  |  |
| 9 | `completed` | datetime | Y |  | MUL |  |  |
| 10 | `progress` | float | Y |  |  |  |  |
| 11 | `attempts` | tinyint unsigned | Y | 0 |  |  |  |
| 12 | `failed` | int | N | 0 |  |  |  |
| 13 | `failure_message` | text | Y |  |  |  |  |
| 14 | `workerkey` | varchar(45) | Y |  |  |  |  |
| 15 | `status` | varchar(255) | Y |  |  |  |  |
| 16 | `priority` | int | N | 5 |  |  |  |

---

### `schema_migrations`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `class` | varchar(255) | N |  |  |  |  |
| 3 | `type` | varchar(50) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `sessions`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | varchar(255) | N |  | PRI |  |  |
| 2 | `user_id` | bigint | Y |  | MUL |  | -> `users` *(inferred)* |
| 3 | `ip_address` | varchar(45) | Y |  |  |  |  |
| 4 | `user_agent` | text | Y |  |  |  |  |
| 5 | `payload` | longtext | N |  |  |  |  |
| 6 | `last_activity` | int | N |  | MUL |  |  |

---

### `updates`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `version_from` | varchar(128) | Y |  |  |  |  |
| 3 | `version_to` | varchar(128) | Y |  |  |  |  |
| 4 | `created` | datetime | Y |  |  |  |  |

---

### `v3_upgrade_pending_changes`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `table_name` | varchar(255) | Y |  |  |  |  |
| 3 | `column` | varchar(128) | Y |  |  |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `pending_value` | varchar(255) | Y |  |  |  |  |

---
