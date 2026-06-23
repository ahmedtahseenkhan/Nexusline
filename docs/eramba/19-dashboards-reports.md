# 19. Dashboards, Reports & Visualisations

Reporting & analytics: dashboards, KPIs and thresholds, report templates/blocks (tables, charts, calendars, task lists, text) and visualisations/sharing.

**Tables in this module:** 28  ·  **Populated:** 11  ·  Back to [index](00-index.md)

**Table list:** `dashboard_calendar_events`, `dashboard_kpi_attributes`, `dashboard_kpi_logs`, `dashboard_kpi_thresholds`, `dashboard_kpi_value_logs`, `dashboard_kpi_values`, `dashboard_kpis`, `dashboard_logs`, `object_status_object_statuses`, `object_status_statuses`, `report_block_calendar_settings`, `report_block_chart_settings`, `report_block_filter_settings`, `report_block_table_fields`, `report_block_table_settings`, `report_block_tasklist_setting_tasks`, `report_block_tasklist_settings`, `report_block_text_settings`, `report_blocks`, `report_templates`, `reports`, `visualisation_settings`, `visualisation_settings_groups`, `visualisation_settings_users`, `visualisation_share`, `visualisation_share_groups`, `visualisation_share_users`, `widget_views`

---

### `dashboard_calendar_events`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `title` | varchar(255) | N |  |  |  |  |
| 5 | `object_title` | varchar(255) | N |  |  |  |  |
| 6 | `start` | date | N |  |  |  |  |
| 7 | `end` | date | Y |  |  |  |  |
| 8 | `expired` | int | N | 0 |  |  |  |
| 9 | `completed` | int | N | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `dashboard_kpi_attributes`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `kpi_id` | int | N |  | MUL |  | FK -> `dashboard_kpis`.id |
| 3 | `model` | varchar(128) | Y |  |  |  |  |
| 4 | `foreign_key` | varchar(128) | N |  |  |  | -> polymorphic (see `model` column) |

---

### `dashboard_kpi_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `kpi_id` | int | N | 0 | MUL |  | FK -> `dashboard_kpis`.id |
| 3 | `value` | int | N |  |  |  |  |
| 4 | `timestamp` | int | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `dashboard_kpi_thresholds`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `kpi_id` | int | N |  | MUL |  | FK -> `dashboard_kpis`.id |
| 3 | `title` | varchar(155) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `color` | text | N |  |  |  |  |
| 6 | `type` | int | N | 0 |  |  |  |
| 7 | `min` | int | Y |  |  |  |  |
| 8 | `max` | int | Y |  |  |  |  |
| 9 | `percentage` | int | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `dashboard_kpi_value_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `kpi_value_id` | int | N | 0 | MUL |  | FK -> `dashboard_kpi_values`.id |
| 3 | `kpi_id` | int | N | 0 |  |  |  |
| 4 | `value` | int | N | 0 |  |  |  |
| 5 | `request_id` | varchar(36) | Y |  |  |  |  |
| 6 | `timestamp` | int | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

---

### `dashboard_kpi_values`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `kpi_id` | int | N |  | MUL |  | FK -> `dashboard_kpis`.id |
| 3 | `user_id` | int | Y |  |  |  | -> `users` *(inferred)* |
| 4 | `value` | int | Y |  |  |  |  |
| 5 | `type` | int | N | 0 |  |  |  |

**Referenced by (FK):** `dashboard_kpi_value_logs`.kpi_value_id

---

### `dashboard_kpis`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `class_name` | varchar(155) | Y |  |  |  |  |
| 3 | `title` | varchar(155) | Y |  |  |  |  |
| 4 | `model` | varchar(155) | N |  |  |  |  |
| 5 | `type` | int | N | 0 |  |  |  |
| 6 | `category` | int | N | 0 |  |  |  |
| 7 | `owner_id` | int | Y |  |  |  |  |
| 8 | `dashboard_kpi_attribute_count` | int | N | 0 |  |  |  |
| 9 | `json` | text | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `value` | int | Y |  |  |  |  |
| 13 | `status` | int | N | 0 |  |  |  |

**Referenced by (FK):** `dashboard_kpi_attributes`.kpi_id, `dashboard_kpi_logs`.kpi_id, `dashboard_kpi_thresholds`.kpi_id, `dashboard_kpi_values`.kpi_id

---

### `dashboard_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N |  |  |  |  |
| 3 | `created` | datetime | N |  |  |  |  |

---

### `object_status_object_statuses`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(100) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  | MUL |  | -> polymorphic (see `model` column) |
| 4 | `name` | varchar(100) | N |  |  |  |  |
| 5 | `status` | int | N |  |  |  |  |
| 6 | `status_id` | int | N |  | MUL |  | FK -> `object_status_statuses`.id |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `object_status_statuses`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(50) | N |  |  |  |  |
| 3 | `name` | varchar(50) | N |  |  |  |  |

**Referenced by (FK):** `object_status_object_statuses`.status_id

---

### `report_block_calendar_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `content` | text | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `report_block_chart_settings`

*Rows: 111*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `chart_id` | varchar(255) | Y |  |  |  |  |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `visualisations` | int | N | 1 |  |  |  |
| 6 | `content` | text | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `dynamic_statuses_report_block_chart_settings`.report_block_chart_setting_id

---

### `report_block_filter_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `advanced_filter_id` | int | Y |  | MUL |  | FK -> `advanced_filters`.id |
| 4 | `filter_id` | int | Y |  | MUL |  | FK -> `filters`.id |
| 5 | `model` | varchar(255) | N |  |  |  |  |
| 6 | `type` | int | N | 1 |  |  |  |
| 7 | `visualisations` | int | N | 1 |  |  |  |
| 8 | `color` | varchar(255) | Y |  |  |  |  |
| 9 | `content` | text | N |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |

---

### `report_block_table_fields`

*Rows: 169*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_table_setting_id` | int | N |  | MUL |  | FK -> `report_block_table_settings`.id |
| 3 | `field` | varchar(255) | N |  |  |  |  |
| 4 | `order` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `report_block_table_settings`

*Rows: 41*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `model` | varchar(255) | N |  |  |  |  |
| 4 | `content` | text | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `report_block_table_fields`.report_block_table_setting_id

---

### `report_block_tasklist_setting_tasks`

*Rows: 87*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_tasklist_setting_id` | int | N |  | MUL |  | FK -> `report_block_tasklist_settings`.id |
| 3 | `task` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `report_block_tasklist_settings`

*Rows: 6*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `content` | text | N |  |  |  |  |
| 4 | `type` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `report_block_tasklist_setting_tasks`.report_block_tasklist_setting_id

---

### `report_block_text_settings`

*Rows: 29*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_block_id` | int | N |  | MUL |  | FK -> `report_blocks`.id |
| 3 | `content` | text | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `report_blocks`

*Rows: 187*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_template_id` | int | N |  | MUL |  | FK -> `report_templates`.id |
| 3 | `parent_id` | int | Y |  | MUL |  | FK -> `report_blocks`.id |
| 4 | `type` | int | N |  |  |  |  |
| 5 | `design` | int | N | 1 |  |  |  |
| 6 | `size` | int | N | 1 |  |  |  |
| 7 | `order` | int | N |  |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `report_block_calendar_settings`.report_block_id, `report_block_chart_settings`.report_block_id, `report_block_filter_settings`.report_block_id, `report_block_table_settings`.report_block_id, `report_block_tasklist_settings`.report_block_id, `report_block_text_settings`.report_block_id, `report_blocks`.parent_id

---

### `report_templates`

*Rows: 30*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `type` | int | N |  |  |  |  |
| 4 | `format` | int | N | 1 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `report_blocks`.report_template_id, `reports`.report_template_id

---

### `reports`

*Rows: 30*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `report_template_id` | int | N |  | MUL |  | FK -> `report_templates`.id |
| 3 | `slug` | varchar(255) | Y |  |  |  |  |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 6 | `name` | varchar(255) | N |  |  |  |  |
| 7 | `protected` | int | N | 0 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `notification_system_items`.feedback_report_id, `notification_system_items`.report_id, `vendor_assessments`.report_id

---

### `visualisation_settings`

*Rows: 77*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  |  |  |  |
| 3 | `status` | int | N | 0 |  |  |  |
| 4 | `order` | int | N | 999 |  |  |  |

**Referenced by (FK):** `visualisation_settings_groups`.visualisation_setting_id, `visualisation_settings_users`.visualisation_setting_id

---

### `visualisation_settings_groups`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `visualisation_setting_id` | int | N |  | MUL |  | FK -> `visualisation_settings`.id |
| 3 | `aros_acos_id` | int | Y |  | MUL |  | FK -> `aros_acos`.id |
| 4 | `user_fields_group_id` | int | Y |  | MUL |  | FK -> `user_fields_groups`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `visualisation_settings_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `visualisation_setting_id` | int | N |  | MUL |  | FK -> `visualisation_settings`.id |
| 3 | `aros_acos_id` | int | Y |  | MUL |  | FK -> `aros_acos`.id |
| 4 | `user_fields_user_id` | int | Y |  | MUL |  | FK -> `user_fields_users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `visualisation_share`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(128) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |

**Referenced by (FK):** `visualisation_share_groups`.visualisation_share_id, `visualisation_share_users`.visualisation_share_id

---

### `visualisation_share_groups`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `visualisation_share_id` | int | N |  | MUL |  | FK -> `visualisation_share`.id |
| 3 | `aros_acos_id` | int | Y |  | MUL |  | FK -> `aros_acos`.id |
| 4 | `user_fields_group_id` | int | Y |  | MUL |  | FK -> `user_fields_groups`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `visualisation_share_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `visualisation_share_id` | int | N |  | MUL |  | FK -> `visualisation_share`.id |
| 3 | `aros_acos_id` | int | Y |  | MUL |  | FK -> `aros_acos`.id |
| 4 | `user_fields_user_id` | int | Y |  | MUL |  | FK -> `user_fields_users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `widget_views`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `widget_view` | datetime | N |  |  |  |  |
| 6 | `comments_view` | datetime | N |  |  |  |  |
| 7 | `attachments_view` | datetime | N |  |  |  |  |

---
