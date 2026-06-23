# 21. Notifications

Notification system: configurable notification items, recipients (users/roles), emails, in-app notifications and delivery logs/feedback.

**Tables in this module:** 12  ·  **Populated:** 1  ·  Back to [index](00-index.md)

**Table list:** `admin_email_notifications`, `app_notification_views`, `app_notifications`, `notification_system_item_custom_roles`, `notification_system_item_custom_users`, `notification_system_item_emails`, `notification_system_item_feedbacks`, `notification_system_item_logs`, `notification_system_items`, `notification_system_items_objects`, `notification_system_items_users`, `notifications`

---

### `admin_email_notifications`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `event_type` | varchar(64) | N |  | MUL |  |  |
| 3 | `occurrence_key` | varchar(191) | N |  |  |  |  |
| 4 | `subject` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `app_notification_views`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `notifications_view` | datetime | N |  |  |  |  |

---

### `app_notifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `notification` | varchar(255) | N |  |  |  |  |
| 3 | `title` | varchar(255) | Y |  |  |  |  |
| 4 | `data` | text | Y |  |  |  |  |
| 5 | `model` | varchar(255) | Y |  |  |  |  |
| 6 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 7 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 8 | `reference` | varchar(255) | Y |  | MUL |  |  |
| 9 | `seen` | tinyint(1) | N |  |  |  |  |
| 10 | `flash_message` | tinyint | N | 0 |  |  |  |
| 11 | `created` | datetime | N |  | MUL |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |

---

### `notification_system_item_custom_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 0 |  |  |  |
| 3 | `notification_system_item_id` | int | N |  | MUL |  | FK -> `notification_system_items`.id |
| 4 | `custom_identifier` | varchar(255) | Y |  |  |  |  |
| 5 | `migration_updated` | int | N | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `notification_system_item_custom_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `notification_system_item_object_id` | int | N |  | MUL |  | FK -> `notification_system_items_objects`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `notification_system_item_emails`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 0 |  |  |  |
| 3 | `notification_system_item_id` | int | N |  | MUL |  | FK -> `notification_system_items`.id |
| 4 | `email` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `notification_system_item_feedbacks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `notification_system_item_log_id` | int | N |  | MUL |  | FK -> `notification_system_item_logs`.id |
| 3 | `notification_system_item_object_id` | int | N |  | MUL |  | FK -> `notification_system_items_objects`.id |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `comment` | text | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `notification_system_item_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `notification_system_item_object_id` | int | N |  | MUL |  | FK -> `notification_system_items_objects`.id |
| 3 | `hash` | text | Y |  |  |  |  |
| 4 | `is_new` | int | N | 1 |  |  |  |
| 5 | `feedback_resolved` | int | Y | 0 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `notification_system_item_feedbacks`.notification_system_item_log_id

---

### `notification_system_items`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `slug` | varchar(255) | Y |  |  |  |  |
| 3 | `status` | int | N | 1 |  |  |  |
| 4 | `name` | varchar(255) | N |  |  |  |  |
| 5 | `description` | text | N |  |  |  |  |
| 6 | `model` | varchar(255) | N |  |  |  |  |
| 7 | `filename` | varchar(255) | N |  |  |  |  |
| 8 | `allow_notification` | int | N | 1 |  |  |  |
| 9 | `allow_webhook` | int | N |  |  |  |  |
| 10 | `allow_trigger` | int | N | 0 |  |  |  |
| 11 | `trigger_id` | int | Y |  | MUL |  | FK -> `triggers`.id |
| 12 | `feedback` | int | N | 0 |  |  |  |
| 13 | `feedback_message` | text | N |  |  |  |  |
| 14 | `chase_interval` | int | Y |  |  |  |  |
| 15 | `chase_amount` | int | Y |  |  |  |  |
| 16 | `trigger_period` | int | Y |  |  |  |  |
| 17 | `automated` | int | N | 1 |  |  |  |
| 18 | `email_customized` | int | N | 1 |  |  |  |
| 19 | `email_subject` | varchar(255) | N |  |  |  |  |
| 20 | `email_body` | text | N |  |  |  |  |
| 21 | `email_type` | int | N | 0 |  |  |  |
| 22 | `report_send_empty_results` | int unsigned | Y |  |  |  |  |
| 23 | `report_attachment_type` | int unsigned | Y |  |  |  |  |
| 24 | `advanced_filter_id` | int | Y |  | MUL |  | FK -> `advanced_filters`.id |
| 25 | `filter_id` | int | Y |  | MUL |  | FK -> `filters`.id |
| 26 | `report_id` | int | Y |  | MUL |  | FK -> `reports`.id |
| 27 | `dynamic_status_id` | int | Y |  | MUL |  | FK -> `dynamic_statuses`.id |
| 28 | `dynamic_status_toggle` | int | Y |  |  |  |  |
| 29 | `type` | varchar(45) | N |  |  |  |  |
| 30 | `status_feedback` | int | N | 0 |  |  |  |
| 31 | `feedback_show_item` | int | N | 0 |  |  |  |
| 32 | `feedback_report_id` | int | Y |  | MUL |  | FK -> `reports`.id |
| 33 | `feedback_completed_notification` | int | N | 0 |  |  |  |
| 34 | `log_count` | int | N |  |  |  |  |
| 35 | `created` | datetime | N |  |  |  |  |
| 36 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `notification_system_item_custom_roles`.notification_system_item_id, `notification_system_item_emails`.notification_system_item_id, `notification_system_items_objects`.notification_system_item_id, `notification_system_items_users`.notification_system_item_id

---

### `notification_system_items_objects`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `notification_system_item_id` | int | N |  | MUL |  | FK -> `notification_system_items`.id |
| 3 | `model` | varchar(250) | N |  |  |  |  |
| 4 | `foreign_key` | int | Y |  |  |  | -> polymorphic (see `model` column) |
| 5 | `status_feedback` | int | N | 0 |  |  |  |
| 6 | `log_count` | int | N |  |  |  |  |
| 7 | `status` | int | N | 1 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `notification_system_item_custom_users`.notification_system_item_object_id, `notification_system_item_feedbacks`.notification_system_item_object_id, `notification_system_item_logs`.notification_system_item_object_id

---

### `notification_system_items_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N | 0 |  |  |  |
| 3 | `notification_system_item_id` | int | N |  | MUL |  | FK -> `notification_system_items`.id |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |

---

### `notifications`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `model` | varchar(150) | N |  |  |  |  |
| 4 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 5 | `url` | varchar(255) | Y |  |  |  |  |
| 6 | `status` | int | N | 1 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---
