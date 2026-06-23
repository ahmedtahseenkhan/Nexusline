# 18. Custom Fields, Forms & Customization

Tenant customization: custom fields & forms, custom labels, user-defined fields, custom validators, translations, tooltips, suggestions and field-data mapping.

**Tables in this module:** 21  ·  **Populated:** 8  ·  Back to [index](00-index.md)

**Table list:** `custom_field_options`, `custom_field_settings`, `custom_field_values`, `custom_fields`, `custom_forms`, `custom_labels`, `custom_validator_fields`, `custom_validator_forms`, `form_organization_entities`, `mapping_relations`, `news`, `purifier_tags`, `setting_groups`, `settings`, `suggestion_settings`, `suggestions`, `tooltip_logs`, `translations`, `user_fields_groups`, `user_fields_objects`, `user_fields_users`

---

### `custom_field_options`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `custom_field_id` | int | N |  | MUL |  | FK -> `custom_fields`.id |
| 3 | `value` | varchar(155) | N |  |  |  |  |

---

### `custom_field_settings`

*Rows: 46*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  | MUL |  |  |
| 3 | `status` | int | N | 0 |  |  |  |

---

### `custom_field_values`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  | MUL |  |  |
| 3 | `foreign_key` | int | N |  | MUL |  | -> polymorphic (see `model` column) |
| 4 | `custom_field_id` | int | N |  | MUL |  | FK -> `custom_fields`.id |
| 5 | `value` | text | Y |  |  |  |  |

---

### `custom_fields`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | Y |  |  |  |  |
| 3 | `relationship_destination` | varchar(255) | Y |  |  |  |  |
| 4 | `custom_form_id` | int | Y |  | MUL |  | FK -> `custom_forms`.id |
| 5 | `name` | varchar(255) | N |  |  |  |  |
| 6 | `slug` | varchar(255) | N |  | UNI |  |  |
| 7 | `type` | int | N |  |  |  |  |
| 8 | `module_relationship_type` | int | N |  |  |  |  |
| 9 | `mandatory` | int | N | 0 |  |  |  |
| 10 | `description` | text | N |  |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `custom_field_options`.custom_field_id, `custom_field_values`.custom_field_id

---

### `custom_forms`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(155) | N |  | MUL |  |  |
| 3 | `name` | varchar(155) | N |  |  |  |  |
| 4 | `slug` | varchar(155) | N |  | UNI |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `custom_fields`.custom_form_id

---

### `custom_labels`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `type` | int | N |  |  |  |  |
| 3 | `model` | varchar(255) | N |  |  |  |  |
| 4 | `subject` | varchar(255) | N |  |  |  |  |
| 5 | `label` | varchar(255) | Y |  |  |  |  |
| 6 | `description` | text | Y |  |  |  |  |
| 7 | `hidden` | int | Y |  |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

---

### `custom_validator_fields`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `validator` | varchar(255) | N |  | MUL |  |  |
| 4 | `field` | varchar(255) | N |  |  |  |  |
| 5 | `type` | int | N |  |  |  |  |
| 6 | `validation` | text | Y |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `custom_validator_forms`

*Rows: 12*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `validator` | varchar(255) | N |  | MUL |  |  |

---

### `form_organization_entities`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `parent_id` | int | Y |  | MUL |  | FK -> `form_organization_entities`.id |
| 3 | `model` | varchar(255) | N |  |  |  |  |
| 4 | `form` | varchar(255) | N |  |  |  |  |
| 5 | `subject` | varchar(255) | N |  |  |  |  |
| 6 | `position` | int | Y |  |  |  |  |
| 7 | `hidden` | tinyint(1) | Y |  |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `form_organization_entities`.parent_id

---

### `mapping_relations`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `left_model` | varchar(128) | N |  |  |  |  |
| 3 | `left_foreign_key` | int | N |  | MUL |  |  |
| 4 | `right_model` | varchar(128) | N |  |  |  |  |
| 5 | `right_foreign_key` | int | N |  | MUL |  |  |
| 6 | `enabled` | int | N | 1 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `news`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `support_id` | int | N |  |  |  |  |
| 3 | `title` | varchar(255) | N |  |  |  |  |
| 4 | `content` | text | N |  |  |  |  |
| 5 | `date` | datetime | Y |  |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |

---

### `purifier_tags`

*Rows: 32*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  | UNI |  |  |
| 3 | `attributes` | text | N |  |  |  |  |
| 4 | `active` | tinyint(1) | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `setting_groups`

*Rows: 55*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `slug` | varchar(50) | N |  | UNI |  |  |
| 3 | `parent_slug` | varchar(50) | Y |  | MUL |  | FK -> `setting_groups`.slug |
| 4 | `name` | varchar(150) | Y |  |  |  |  |
| 5 | `icon_code` | varchar(150) | Y |  |  |  |  |
| 6 | `notes` | varchar(250) | Y |  |  |  |  |
| 7 | `url` | varchar(250) | Y |  |  |  |  |
| 8 | `modal` | int | N | 0 |  |  |  |
| 9 | `hidden` | tinyint | Y | 0 |  |  |  |
| 10 | `order` | int | Y | 0 |  |  |  |

**Referenced by (FK):** `setting_groups`.parent_slug, `settings`.setting_group_slug

**Configured values (55):**

| id | slug | parent_slug | name | icon_code | notes | url | modal | hidden | order |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ACCESSLST | ACCESSMGT | Access Lists |  |  | {"controller":"admin", "action":"acl", "0" :"aros", "1":"ajax_role_permissions"} | 0 | 0 | 0 |
| 2 | ACCESSMGT |  | Access Management | icon-cog |  |  | 0 | 0 | 0 |
| 3 | AUTH | ACCESSMGT | Authentication |  |  | {"controller":"ldapConnectorAuthentications","action":"edit"} | 1 | 0 | 0 |
| 4 | BANNER | SEC | Banners |  |  |  | 0 | 1 | 0 |
| 5 | BAR | DB | Backup & Restore |  |  | {"controller":"backupRestore","action":"index", "plugin":"backupRestore"} | 1 | 0 | 0 |
| 6 | BFP | SEC | Brute Force Protection |  | This setting allows you to protect the login page of eramba from being brute-force attacked. |  | 0 | 0 | 0 |
| 7 | CUE | LOC | Currency |  |  |  | 0 | 0 | 0 |
| 8 | DASH |  | Dashboard | icon-cog |  |  | 0 | 0 | 0 |
| 9 | DASHRESET | DASH | Reset Dashboards |  |  | {"controller":"settings","action":"resetDashboards"} | 0 | 0 | 0 |
| 10 | DB |  | Database | icon-cog |  |  | 0 | 0 | 0 |
| 11 | DBCNF | DB | Database Configurations |  |  |  | 0 | 1 | 0 |
| 12 | DBRESET | DB | Reset Database |  |  | {"controller":"settings","action":"resetDatabase"} | 1 | 0 | 0 |
| 13 | DEBUG |  | Debug Settings and Logs | icon-cog |  |  | 0 | 0 | 0 |
| 14 | DEBUGCFG | DEBUG | Debug Config |  |  |  | 0 | 0 | 0 |
| 15 | ERRORLOG | DEBUG | Error Log |  |  | {"controller":"settings","action":"logs", "0":"error"} | 1 | 0 | 0 |
| 16 | GROUP | ACCESSMGT | Groups |  |  | {"controller":"groups","action":"index"} | 0 | 0 | 0 |
| 17 | LDAP | ACCESSMGT | LDAP Connectors |  |  | {"controller":"ldapConnectors","action":"index"} | 0 | 0 | 0 |
| 18 | LOC |  | Localization | icon-cog |  |  | 0 | 0 | 0 |
| 19 | MAIL |  | Mail | icon-cog |  |  | 0 | 0 | 0 |
| 20 | MAILCNF | MAIL | Mail Configurations |  |  |  | 0 | 0 | 0 |
| 21 | MAILLOG | DEBUG | Email Log |  |  | {"controller":"settings","action":"logs", "0":"email"} | 1 | 0 | 0 |
| 22 | PRELOAD | DB | Pre-load the database with default databases |  |  |  | 0 | 1 | 0 |
| 23 | RISK |  | Risk | icon-cog |  |  | 0 | 1 | 0 |
| 24 | RISKAPPETITE | RISK | Risk appetite |  |  |  | 0 | 0 | 0 |
| 25 | ROLES | ACCESSMGT | Roles |  |  | {"controller":"scopes","action":"index"} | 0 | 1 | 0 |
| 26 | SEC |  | Security | icon-cog |  |  | 0 | 0 | 0 |
| 27 | SECKEY | CRONJOBS | Crontab Security Key |  |  |  | 0 | 0 | 0 |
| 28 | USER | ACCESSMGT | User Management |  |  | {"controller":"users","action":"index"} | 0 | 0 | 0 |
| 29 | CLRCACHE | DEBUG | Clear Cache |  |  | {"controller":"settings","action":"deleteCache"} | 0 | 0 | 0 |
| 30 | CLRACLCACHE | DEBUG | Clear ACL Cache |  |  | {"controller":"settings","action":"deleteCache", "0":"acl"} | 0 | 1 | 0 |
| 31 | LOGO | LOC | Custom Logo |  |  | {"controller":"settings","action":"customLogo"} | 1 | 0 | 0 |
| 32 | HEALTH | SEC | System Health |  |  | {"controller":"settings","action":"systemHealth"} | 1 | 0 | 0 |
| 33 | TZONE | LOC | Timezone |  |  |  | 0 | 0 | 0 |
| 34 | UPDATES | SEC | Updates |  |  | {"controller":"updates","action":"index"} | 0 | 0 | 0 |
| 35 | NOTIFICATION | ACCESSMGT | Notifications |  |  | {"controller":"notificationSystem","action":"listItems"} | 0 | 1 | 0 |
| 36 | CRON | CRONJOBS | Crontab History |  |  | {"controller":"cron","action":"index"} | 0 | 0 | 0 |
| 37 | BACKUP | DB | Backup Configuration |  |  |  | 0 | 0 | 2 |
| 38 | QUEUE | MAIL | Emails In Queue |  |  | {"controller":"queue", "action":"index"} | 0 | 0 | 0 |
| 39 | VISUALISATION | ACCESSMGT | Visualisation |  |  | {"controller":"visualisationSettings","action":"index", "plugin":"visualisation"} | 0 | 0 | 0 |
| 40 | OAUTH | ACCESSMGT | OAuth Connectors |  |  | {"controller":"oauthConnectors","action":"index"} | 0 | 0 | 0 |
| 41 | CRONJOBS |  | Cron Jobs | icon-cog |  |  | 0 | 0 | 0 |
| 42 | GENERAL |  | General Settings | icon-cog |  |  | 0 | 0 | 0 |
| 43 | PDFCONFIG | GENERAL | PDF Configuration |  |  |  | 0 | 0 | 0 |
| 44 | SSLOFFLOAD | SEC | SSL/TLS Offload |  |  |  | 0 | 0 | 0 |
| 45 | ENTERPRISE_USERS | SEC | Enterprise Users |  |  |  | 0 | 0 | 0 |
| 46 | SECSALT | SEC | Security Salt |  |  |  | 0 | 1 | 0 |
| 47 | CSV | LOC | CSV Delimiter |  |  |  | 0 | 0 | 0 |
| 48 | TRANSLATION | LOC | Languages |  |  | {"plugin":"translations","controller":"translations","action":"index"} | 0 | 0 | 0 |
| 49 | DEFAULT_TRANSLATION | LOC | Default Language |  |  |  | 1 | 1 | 0 |
| 50 | WEBHOOKS |  | Webhooks Configuration |  |  |  | 1 | 0 | 0 |
| 51 | DASHBOARD | LOC | Dashboard Template |  |  | {"plugin":"dashboard","controller":"dashboardReports","action":"index"} | 0 | 0 | 0 |
| 52 | DEFAULT_DASHBOARD | LOC | Active Dashboard |  |  |  | 1 | 1 | 0 |
| 53 | SENDDIAGNOSTICS | DEBUG | Help Improve Eramba |  |  | {"plugin":false,"controller":"settings","action":"helpImprove"} | 1 | 0 | 0 |
| 54 | ACTIVITY_LOG |  | Activity Log Configuration |  |  | {"plugin":false,"controller":"settings","action":"helpImprove"} | 1 | 0 | 0 |
| 55 | UI |  | Legacy UI |  |  | {"plugin":false,"controller":"settings","action":"helpImprove"} | 1 | 0 | 0 |

---

### `settings`

*Rows: 47*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `active` | int | N | 1 |  |  |  |
| 3 | `name` | varchar(255) | N |  |  |  |  |
| 4 | `variable` | varchar(100) | N |  |  |  |  |
| 5 | `value` | varchar(255) | Y |  |  |  |  |
| 6 | `default_value` | varchar(255) | Y |  |  |  |  |
| 7 | `values` | varchar(255) | Y |  |  |  |  |
| 8 | `type` | varchar(255) | N | text |  |  |  |
| 9 | `options` | varchar(150) | Y |  |  |  |  |
| 10 | `hidden` | int | N | 0 |  |  |  |
| 11 | `required` | int | N | 0 |  |  |  |
| 12 | `setting_group_slug` | varchar(50) | Y |  | MUL |  | FK -> `setting_groups`.slug |
| 13 | `setting_type` | varchar(255) | Y | constant |  |  |  |
| 14 | `order` | int | N | 0 |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |
| 16 | `created` | datetime | N |  |  |  |  |

---

### `suggestion_settings`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `value` | int | N |  |  |  |  |

---

### `suggestions`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `suggestion` | varchar(255) | N |  |  |  |  |
| 3 | `model` | varchar(155) | N |  |  |  |  |
| 4 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 5 | `created` | datetime | N |  |  |  |  |

---

### `tooltip_logs`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 3 | `seen` | int | N | 0 |  |  |  |
| 4 | `model` | varchar(255) | N |  |  |  |  |
| 5 | `type` | varchar(30) | N |  |  |  |  |
| 6 | `file_id` | int | N |  |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |

---

### `translations`

*Rows: 26*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `folder` | varchar(255) | N |  |  |  |  |
| 4 | `status` | int | N | 1 |  |  |  |
| 5 | `type` | int | N | 1 |  |  |  |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

---

### `user_fields_groups`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `field` | varchar(255) | N |  |  |  |  |
| 5 | `group_id` | int | N |  | MUL |  | FK -> `groups`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `visualisation_settings_groups`.user_fields_group_id, `visualisation_share_groups`.user_fields_group_id

---

### `user_fields_objects`

*Rows: 24*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `field` | varchar(255) | N |  |  |  |  |
| 5 | `object_id` | int | N |  |  |  |  |
| 6 | `object_key` | varchar(255) | N |  |  |  |  |
| 7 | `object_model` | varchar(255) | N |  |  |  |  |
| 8 | `created` | datetime | N |  |  |  |  |
| 9 | `modified` | datetime | N |  |  |  |  |

---

### `user_fields_users`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `model` | varchar(255) | N |  |  |  |  |
| 3 | `foreign_key` | int | N |  |  |  | -> polymorphic (see `model` column) |
| 4 | `field` | varchar(255) | N |  |  |  |  |
| 5 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 6 | `created` | datetime | N |  |  |  |  |
| 7 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `visualisation_settings_users`.user_fields_user_id, `visualisation_share_users`.user_fields_user_id

---
