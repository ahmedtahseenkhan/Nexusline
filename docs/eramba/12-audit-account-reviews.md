# 12. Audit Management & Account Reviews

Account reviews (access certification) feature: review feeds, pulls, rows, feedbacks and findings used to certify user access.

**Tables in this module:** 12  ·  **Populated:** 0  ·  Back to [index](00-index.md)

**Table list:** `account_review_feed_ldap_groups`, `account_review_feed_pulls`, `account_review_feed_row_roles`, `account_review_feed_rows`, `account_review_feedback_roles`, `account_review_feedbacks`, `account_review_feeds`, `account_review_findings`, `account_review_findings_feedbacks`, `account_review_pulls`, `account_reviews`, `account_reviews_assets`

---

### `account_review_feed_ldap_groups`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_feed_id` | int | N |  | MUL |  | FK -> `account_review_feeds`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |

---

### `account_review_feed_pulls`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_feed_id` | int | N |  | MUL |  | FK -> `account_review_feeds`.id |
| 3 | `account_review_pull_id` | int | N |  | MUL |  | FK -> `account_review_pulls`.id |
| 4 | `status` | int | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |
| 7 | `deleted` | int | N | 0 |  |  |  |
| 8 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feed_rows`.account_review_feed_pull_id

---

### `account_review_feed_row_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_feed_row_id` | int | N |  | MUL |  | FK -> `account_review_feed_rows`.id |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `created` | datetime | N |  |  |  |  |

---

### `account_review_feed_rows`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_feed_id` | int | N |  | MUL |  | FK -> `account_review_feeds`.id |
| 3 | `account_review_feed_pull_id` | int | N |  | MUL |  | FK -> `account_review_feed_pulls`.id |
| 4 | `user` | varchar(255) | N |  |  |  |  |
| 5 | `description` | varchar(255) | N |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

**Referenced by (FK):** `account_review_feed_row_roles`.account_review_feed_row_id

---

### `account_review_feedback_roles`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_feedback_id` | int | N |  | MUL |  | FK -> `account_review_feedbacks`.id |
| 3 | `type` | int | Y |  |  |  |  |
| 4 | `name` | varchar(255) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `account_review_feedbacks`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_pull_id` | int | N |  | MUL |  | FK -> `account_review_pulls`.id |
| 3 | `type` | int | N |  |  |  |  |
| 4 | `user` | varchar(255) | N |  |  |  |  |
| 5 | `description` | varchar(255) | N |  |  |  |  |
| 6 | `answer` | int | Y |  |  |  |  |
| 7 | `locked` | int | N | 0 |  |  |  |
| 8 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 9 | `created` | datetime | N |  |  |  |  |
| 10 | `modified` | datetime | N |  |  |  |  |
| 11 | `edited` | datetime | Y |  |  |  |  |
| 12 | `deleted` | int | N | 0 |  |  |  |
| 13 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feedback_roles`.account_review_feedback_id, `account_review_findings_feedbacks`.account_review_feedback_id

---

### `account_review_feeds`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `title` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `type` | int | N | 1 |  |  |  |
| 5 | `source_type` | int | N | 1 |  |  |  |
| 6 | `trigger_id` | int | Y |  | MUL |  | FK -> `triggers`.id |
| 7 | `path` | text | N |  |  |  |  |
| 8 | `local_file` | text | Y |  |  |  |  |
| 9 | `ldap_connector_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 10 | `aws_key` | varchar(255) | Y |  |  |  |  |
| 11 | `aws_secret` | varchar(255) | Y |  |  |  |  |
| 12 | `aws_region` | varchar(255) | Y |  |  |  |  |
| 13 | `created` | datetime | N |  |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |
| 15 | `deleted` | int | N | 0 |  |  |  |
| 16 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feed_ldap_groups`.account_review_feed_id, `account_review_feed_pulls`.account_review_feed_id, `account_review_feed_rows`.account_review_feed_id, `account_reviews`.account_review_feed_id, `account_reviews`.comparison_account_review_feed_id

---

### `account_review_findings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_pull_id` | int | N |  | MUL |  | FK -> `account_review_pulls`.id |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `deadline` | date | N |  |  |  |  |
| 6 | `close_date` | date | Y |  |  |  |  |
| 7 | `auto_close_date` | int | N | 1 |  |  |  |
| 8 | `status` | int | N |  |  |  |  |
| 9 | `expired` | int | N | 0 |  |  |  |
| 10 | `created` | datetime | N |  |  |  |  |
| 11 | `modified` | datetime | N |  |  |  |  |
| 12 | `edited` | datetime | Y |  |  |  |  |
| 13 | `deleted` | int | N | 0 |  |  |  |
| 14 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_findings_feedbacks`.account_review_finding_id

---

### `account_review_findings_feedbacks`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_finding_id` | int | N |  | MUL |  | FK -> `account_review_findings`.id |
| 3 | `account_review_feedback_id` | int | N |  | MUL |  | FK -> `account_review_feedbacks`.id |

---

### `account_review_pulls`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `hash` | varchar(255) | N |  |  |  |  |
| 3 | `account_review_id` | int | N |  | MUL |  | FK -> `account_reviews`.id |
| 4 | `status` | int | N |  |  |  |  |
| 5 | `submitted` | int | N | 0 |  |  |  |
| 6 | `submit_date` | datetime | Y |  |  |  |  |
| 7 | `count_check` | int | N | 0 |  |  |  |
| 8 | `count_added` | int | N | 0 |  |  |  |
| 9 | `count_deleted` | int | N | 0 |  |  |  |
| 10 | `count_current_check` | int | N | 0 |  |  |  |
| 11 | `count_former_check` | int | N | 0 |  |  |  |
| 12 | `count_role_change` | int | N | 0 |  |  |  |
| 13 | `is_manual` | int | N | 0 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `edited` | datetime | Y |  |  |  |  |
| 17 | `deleted` | int | N | 0 |  |  |  |
| 18 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feed_pulls`.account_review_pull_id, `account_review_feedbacks`.account_review_pull_id, `account_review_findings`.account_review_pull_id

---

### `account_reviews`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `hash` | varchar(255) | N |  |  |  |  |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `description` | text | N |  |  |  |  |
| 5 | `type` | int | N |  |  |  |  |
| 6 | `frequency` | int | N |  |  |  |  |
| 7 | `frequency_type` | int | N |  |  |  |  |
| 8 | `comparison_type` | int | N |  |  |  |  |
| 9 | `account_review_feed_id` | int | Y |  | MUL |  | FK -> `account_review_feeds`.id |
| 10 | `comparison_account_review_feed_id` | int | Y |  | MUL |  | FK -> `account_review_feeds`.id |
| 11 | `portal_title` | varchar(255) | N |  |  |  |  |
| 12 | `portal_description` | text | N |  |  |  |  |
| 13 | `incomplete_submit` | int | N | 0 |  |  |  |
| 14 | `auto_submit_empty` | int | N | 1 |  |  |  |
| 15 | `status` | int | N | 0 |  |  |  |
| 16 | `created` | datetime | N |  |  |  |  |
| 17 | `modified` | datetime | N |  |  |  |  |
| 18 | `edited` | datetime | Y |  |  |  |  |
| 19 | `deleted` | int | N | 0 |  |  |  |
| 20 | `deleted_date` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_pulls`.account_review_id, `account_reviews_assets`.account_review_id

---

### `account_reviews_assets`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `account_review_id` | int | N |  | MUL |  | FK -> `account_reviews`.id |
| 3 | `asset_id` | int | N |  | MUL |  | FK -> `assets`.id |

---
