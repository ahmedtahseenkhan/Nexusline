# 20. Filters & Advanced Filters

Saved filters and advanced (scheduled) filter engine used to slice grids and drive notifications/reports.

**Tables in this module:** 8  ·  **Populated:** 4  ·  Back to [index](00-index.md)

**Table list:** `advanced_filter_cron_result_items`, `advanced_filter_crons`, `advanced_filter_user_params`, `advanced_filter_user_settings`, `advanced_filter_values`, `advanced_filters`, `filter_user_settings`, `filters`

---

### `advanced_filter_cron_result_items`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `advanced_filter_cron_id` | int | N |  | MUL |  | FK -> `advanced_filter_crons`.id |
| 3 | `data` | text | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `advanced_filter_crons`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `advanced_filter_id` | int | N |  | MUL |  | FK -> `advanced_filters`.id |
| 3 | `cron_id` | int | Y |  | MUL |  | FK -> `cron`.id |
| 4 | `type` | int | Y |  |  |  |  |
| 5 | `result` | int | Y |  |  |  |  |
| 6 | `execution_time` | float | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `advanced_filter_cron_result_items`.advanced_filter_cron_id

---

### `advanced_filter_user_params`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `advanced_filter_id` | int | N |  | MUL |  | FK -> `advanced_filters`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `type` | int | N | 0 |  |  |  |
| 5 | `param` | varchar(255) | N |  |  |  |  |
| 6 | `value` | text | Y |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

---

### `advanced_filter_user_settings`

*Rows: 67*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `advanced_filter_id` | int | N |  | MUL |  | FK -> `advanced_filters`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `vertical_scroll` | int | N | 0 |  |  |  |
| 5 | `default_index` | int | N | 0 |  |  |  |
| 6 | `limit` | int | N | 10 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `advanced_filter_values`

*Rows: 746*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `advanced_filter_id` | int | N |  | MUL |  | FK -> `advanced_filters`.id |
| 3 | `field` | varchar(255) | N |  |  |  |  |
| 4 | `value` | text | N |  |  |  |  |
| 5 | `many` | int unsigned | N | 0 |  |  |  |

---

### `advanced_filters`

*Rows: 67*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `slug` | varchar(255) | Y |  |  |  |  |
| 5 | `description` | text | N |  |  |  |  |
| 6 | `model` | varchar(255) | N |  |  |  |  |
| 7 | `private` | int | N | 0 |  |  |  |
| 8 | `log_result_count` | int | N |  |  |  |  |
| 9 | `log_result_data` | int | N |  |  |  |  |
| 10 | `system_filter` | int | N | 0 |  |  |  |
| 11 | `deleted` | int | N | 0 |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |
| 13 | `created` | datetime | N |  |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `advanced_filter_crons`.advanced_filter_id, `advanced_filter_user_params`.advanced_filter_id, `advanced_filter_user_settings`.advanced_filter_id, `advanced_filter_values`.advanced_filter_id, `notification_system_items`.advanced_filter_id, `report_block_filter_settings`.advanced_filter_id

---

### `filter_user_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `filter_id` | int | Y |  | MUL |  | FK -> `filters`.id |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `pinned` | tinyint | N | 0 |  |  |  |
| 6 | `default` | tinyint | N | 0 |  |  |  |
| 7 | `params` | text | Y |  |  |  |  |
| 8 | `created` | datetime | Y |  |  |  |  |
| 9 | `modified` | datetime | Y |  |  |  |  |

---

### `filters`

*Rows: 777*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `slug` | varchar(255) | Y |  |  |  |  |
| 4 | `system` | tinyint | N | 0 |  |  |  |
| 5 | `default` | tinyint | N | 0 |  |  |  |
| 6 | `advanced_filter_id` | int | Y |  |  |  | -> `advanced_filters` *(inferred)* |
| 7 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 8 | `can_view_everyone` | tinyint | N | 0 |  |  |  |
| 9 | `can_update_everyone` | tinyint | N | 0 |  |  |  |
| 10 | `model` | varchar(255) | N |  |  |  |  |
| 11 | `params` | text | Y |  |  |  |  |
| 12 | `created` | datetime | N |  |  |  |  |
| 13 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `filter_user_settings`.filter_id, `notification_system_items`.filter_id, `report_block_filter_settings`.filter_id

---
