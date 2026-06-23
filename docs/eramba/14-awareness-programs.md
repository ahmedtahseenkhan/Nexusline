# 14. Awareness Programs

Security awareness training & phishing programs: programs, recurrences/trainings, questionnaires, user compliance tracking and reminders.

**Tables in this module:** 21  ·  **Populated:** 0  ·  Back to [index](00-index.md)

**Table list:** `awareness_overtime_graphs`, `awareness_program_active_users`, `awareness_program_compliant_users`, `awareness_program_demos`, `awareness_program_ignored_users`, `awareness_program_ldap_groups`, `awareness_program_missed_recurrences`, `awareness_program_not_compliant_users`, `awareness_program_questionnaire_options`, `awareness_program_questionnaires`, `awareness_program_recurrence_reminders`, `awareness_program_recurrence_training_answers`, `awareness_program_recurrence_trainings`, `awareness_program_recurrences`, `awareness_program_value_logs`, `awareness_programs`, `awareness_programs_groups`, `awareness_programs_security_policies`, `awareness_reminders_old`, `awareness_trainings_old`, `awareness_users`

---

### `awareness_overtime_graphs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | Y |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `doing` | decimal(8,2) | N |  |  |  |  |
| 5 | `missing` | decimal(8,2) | N |  |  |  |  |
| 6 | `correct_answers` | decimal(8,2) | N |  |  |  |  |
| 7 | `average` | decimal(8,2) | N |  |  |  |  |
| 8 | `timestamp` | varchar(45) | N |  |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_active_users`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `uid` | varchar(100) | Y |  |  |  |  |
| 5 | `email` | varchar(100) | Y |  |  |  |  |
| 6 | `name` | varchar(155) | Y |  |  |  |  |
| 7 | `invitation_date` | date | Y |  |  |  |  |
| 8 | `reminders_last_date` | date | Y |  |  |  |  |
| 9 | `reminders_amount` | int | N | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_compliant_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `uid` | varchar(100) | Y |  |  |  |  |
| 4 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_demos`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `uid` | varchar(100) | N |  |  |  |  |
| 3 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 4 | `completed` | int | N | 0 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `awareness_program_ignored_users`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `uid` | varchar(100) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_ldap_groups`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `name` | varchar(150) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_missed_recurrences`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `uid` | varchar(100) | Y |  |  |  |  |
| 3 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `awareness_program_id` | int | Y |  | MUL |  | FK -> `awareness_programs`.id |
| 5 | `awareness_program_recurrence_id` | int | Y |  | MUL |  | FK -> `awareness_program_recurrences`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `awareness_program_not_compliant_users`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `uid` | varchar(100) | Y |  |  |  |  |
| 4 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `awareness_program_questionnaire_options`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_questionnaire_id` | int | N |  | MUL |  | FK -> `awareness_program_questionnaires`.id |
| 3 | `title` | text | N |  |  |  |  |
| 4 | `index` | int | N |  |  |  |  |
| 5 | `status` | int | N |  |  |  |  |

**Referenced by (FK):** `awareness_program_recurrence_training_answers`.awareness_program_questionnaire_option_id

---

### `awareness_program_questionnaires`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `question` | text | N |  |  |  |  |
| 4 | `description` | text | Y |  |  |  |  |
| 5 | `correct_option` | int | Y |  |  |  |  |

**Referenced by (FK):** `awareness_program_questionnaire_options`.awareness_program_questionnaire_id

---

### `awareness_program_recurrence_reminders`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_recurrence_id` | int | N |  | MUL |  | FK -> `awareness_program_recurrences`.id |
| 3 | `awareness_program_id` | int | Y |  | MUL |  | FK -> `awareness_programs`.id |
| 4 | `uid` | varchar(128) | Y |  | MUL |  |  |
| 5 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 6 | `email` | varchar(128) | N |  |  |  |  |
| 7 | `type` | int | N | 1 |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `deleted_date` | datetime | Y |  |  |  |  |

---

### `awareness_program_recurrence_training_answers`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_recurrence_training_id` | int | N |  | MUL |  | FK -> `awareness_program_recurrence_trainings`.id |
| 3 | `awareness_program_questionnaire_option_id` | int | N |  | MUL |  | FK -> `awareness_program_questionnaire_options`.id |

---

### `awareness_program_recurrence_trainings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `uid` | varchar(100) | Y |  |  |  |  |
| 3 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 4 | `awareness_program_recurrence_id` | int | N |  | MUL |  | FK -> `awareness_program_recurrences`.id |
| 5 | `awareness_program_id` | int | Y |  | MUL |  | FK -> `awareness_programs`.id |
| 6 | `correct_answers` | int | Y |  |  |  |  |
| 7 | `wrong_answers` | int | Y |  |  |  |  |
| 8 | `total_answers` | int | Y |  |  |  |  |
| 9 | `correct_percentage` | int | Y |  |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `awareness_program_recurrence_training_answers`.awareness_program_recurrence_training_id

---

### `awareness_program_recurrences`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `start` | date | N |  |  |  |  |
| 4 | `end` | date | Y |  |  |  |  |
| 5 | `status` | int | N | 0 |  |  |  |
| 6 | `awareness_training_count` | int | N |  |  |  |  |

**Referenced by (FK):** `awareness_program_missed_recurrences`.awareness_program_recurrence_id, `awareness_program_recurrence_reminders`.awareness_program_recurrence_id, `awareness_program_recurrence_trainings`.awareness_program_recurrence_id, `awareness_trainings_old`.awareness_program_recurrence_id

---

### `awareness_program_value_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `field` | varchar(256) | N |  |  |  |  |
| 4 | `value` | int | N | 0 |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `awareness_programs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `recurrence` | int | N |  |  |  |  |
| 5 | `always_available` | int | N | 0 |  |  |  |
| 6 | `reminder_apart` | int | N |  |  |  |  |
| 7 | `reminder_amount` | int | N |  |  |  |  |
| 8 | `enable_reminders` | int | N | 0 |  |  |  |
| 9 | `redirect` | varchar(255) | N |  |  |  |  |
| 10 | `ldap_connector_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 11 | `ldap_check` | varchar(255) | Y |  |  |  |  |
| 12 | `video` | varchar(255) | Y |  |  |  |  |
| 13 | `video_extension` | varchar(50) | Y |  |  |  |  |
| 14 | `video_mime_type` | varchar(150) | Y |  |  |  |  |
| 15 | `video_file_size` | int | Y |  |  |  |  |
| 16 | `questionnaire` | varchar(255) | Y |  |  |  |  |
| 17 | `questionnaire_show_incorrect_answers` | int | N | 0 |  |  |  |
| 18 | `questionnaire_allow_user_to_continue` | int | N | 0 |  |  |  |
| 19 | `text_file` | varchar(255) | Y |  |  |  |  |
| 20 | `text_file_extension` | varchar(50) | Y |  |  |  |  |
| 21 | `text_file_frame_size` | int | Y |  |  |  |  |
| 22 | `uploads_sort_json` | text | N |  |  |  |  |
| 23 | `welcome_text` | text | N |  |  |  |  |
| 24 | `welcome_sub_text` | text | N |  |  |  |  |
| 25 | `thank_you_text` | text | N |  |  |  |  |
| 26 | `thank_you_sub_text` | text | N |  |  |  |  |
| 27 | `email_subject` | varchar(255) | N |  |  |  |  |
| 28 | `email_body` | text | N |  |  |  |  |
| 29 | `email_reminder_custom` | int | N | 0 |  |  |  |
| 30 | `email_reminder_subject` | varchar(255) | N |  |  |  |  |
| 31 | `email_reminder_body` | text | N |  |  |  |  |
| 32 | `status` | varchar(100) | Y | stopped |  |  |  |
| 33 | `demo_mode_enabled` | int | N | 0 |  |  |  |
| 34 | `awareness_training_count` | int | N |  |  |  |  |
| 35 | `active_users` | int | Y |  |  |  |  |
| 36 | `active_users_percentage` | int | Y |  |  |  |  |
| 37 | `ignored_users` | int | Y |  |  |  |  |
| 38 | `ignored_users_percentage` | int | Y |  |  |  |  |
| 39 | `compliant_users` | int | Y |  |  |  |  |
| 40 | `compliant_users_percentage` | int | Y |  |  |  |  |
| 41 | `not_compliant_users` | int | Y |  |  |  |  |
| 42 | `not_compliant_users_percentage` | int | Y |  |  |  |  |
| 43 | `stats_update_status` | int | N | 0 |  |  |  |
| 44 | `workflow_owner_id` | int | Y |  |  |  |  |
| 45 | `workflow_status` | int | N | 0 |  |  |  |
| 46 | `created` | datetime | N |  |  |  |  |
| 47 | `modified` | datetime | N |  |  |  |  |
| 48 | `edited` | datetime | Y |  |  |  |  |
| 49 | `deleted` | int | N | 0 |  |  |  |
| 50 | `deleted_date` | datetime | Y |  |  |  |  |
| 51 | `need_resave` | int | N | 1 |  |  |  |

**Referenced by (FK):** `awareness_overtime_graphs`.awareness_program_id, `awareness_program_active_users`.awareness_program_id, `awareness_program_compliant_users`.awareness_program_id, `awareness_program_demos`.awareness_program_id, `awareness_program_ignored_users`.awareness_program_id, `awareness_program_ldap_groups`.awareness_program_id, `awareness_program_missed_recurrences`.awareness_program_id, `awareness_program_not_compliant_users`.awareness_program_id, `awareness_program_questionnaires`.awareness_program_id, `awareness_program_recurrence_reminders`.awareness_program_id, `awareness_program_recurrence_trainings`.awareness_program_id, `awareness_program_recurrences`.awareness_program_id, `awareness_program_value_logs`.awareness_program_id, `awareness_programs_groups`.awareness_program_id, `awareness_programs_security_policies`.awareness_program_id, `awareness_reminders_old`.awareness_program_id, `awareness_trainings_old`.awareness_program_id

---

### `awareness_programs_groups`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 3 | `group_id` | int | N |  | MUL |  | FK -> `groups`.id |

---

### `awareness_programs_security_policies`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `security_policy_id` | int | N |  | MUL |  | FK -> `security_policies`.id |
| 3 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `awareness_reminders_old`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `uid` | varchar(100) | N |  | MUL |  |  |
| 3 | `email` | varchar(100) | N |  |  |  |  |
| 4 | `awareness_program_id` | int | N |  | MUL |  | FK -> `awareness_programs`.id |
| 5 | `demo` | int | N | 0 |  |  |  |
| 6 | `reminder_type` | int | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |

---

### `awareness_trainings_old`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `uid` | varchar(100) | N |  |  |  |  |
| 3 | `awareness_program_id` | int | Y |  | MUL |  | FK -> `awareness_programs`.id |
| 4 | `awareness_program_recurrence_id` | int | N |  | MUL |  | FK -> `awareness_program_recurrences`.id |
| 5 | `answers_json` | text | Y |  |  |  |  |
| 6 | `correct` | int | Y |  |  |  |  |
| 7 | `wrong` | int | Y |  |  |  |  |
| 8 | `demo` | int | N | 0 |  |  |  |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |

---

### `awareness_users`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `login` | varchar(45) | N |  |  |  |  |
| 3 | `created` | datetime | N |  |  |  |  |

---
