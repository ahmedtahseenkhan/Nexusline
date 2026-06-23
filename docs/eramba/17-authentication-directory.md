# 17. Authentication & Directory Services

Authentication configuration and external identity: local auth settings, LDAP/Active Directory sync, SAML SSO, OAuth login and OAuth2 API tokens.

**Tables in this module:** 15  ·  **Populated:** 2  ·  Back to [index](00-index.md)

**Table list:** `authentication_settings`, `ldap_connector_authentication`, `ldap_connectors`, `ldap_synchronizations`, `ldap_synchronizations_groups`, `ldap_synchronizations_portals`, `oauth2_access_tokens`, `oauth2_authorization_codes`, `oauth2_clients`, `oauth2_refresh_tokens`, `oauth_connectors`, `request_tokens`, `saml_connectors`, `tickets`, `user_tokens`

---

### `authentication_settings`

*Rows: 1*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `auth_main` | int | N | 1 |  |  |  |
| 3 | `ldap_connector_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 4 | `oauth_connector_id` | int | Y |  | MUL |  | FK -> `oauth_connectors`.id |
| 5 | `saml_connector_id` | int | Y |  | MUL |  | FK -> `saml_connectors`.id |
| 6 | `auth_awareness` | int | N | 0 |  |  |  |
| 7 | `auth_awareness_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 8 | `auth_policies` | int | N | 1 |  |  |  |
| 9 | `auth_policies_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 10 | `auth_compliance_audit` | int | N | 1 |  |  |  |
| 11 | `auth_vendor_assessment` | int | N | 1 |  |  |  |
| 12 | `auth_account_review` | int | N | 1 |  |  |  |
| 13 | `auth_mcp` | int unsigned | N | 0 |  |  |  |
| 14 | `modified` | datetime | N |  |  |  |  |

---

### `ldap_connector_authentication`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `auth_users` | int | N |  |  |  |  |
| 3 | `auth_users_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 4 | `oauth_google` | int | N |  |  |  |  |
| 5 | `oauth_google_id` | int | N |  |  |  |  |
| 6 | `auth_saml` | int | N |  |  |  |  |
| 7 | `saml_connector_id` | int | Y |  | MUL |  | FK -> `saml_connectors`.id |
| 8 | `auth_awareness` | int | N |  |  |  |  |
| 9 | `auth_awareness_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 10 | `auth_policies` | int | N |  |  |  |  |
| 11 | `auth_policies_id` | int | Y |  | MUL |  | FK -> `ldap_connectors`.id |
| 12 | `auth_compliance_audit` | int | N | 0 |  |  |  |
| 13 | `auth_vendor_assessment` | int | N | 0 |  |  |  |
| 14 | `auth_account_review` | int | N | 0 |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |

---

### `ldap_connectors`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `description` | text | N |  |  |  |  |
| 4 | `host` | varchar(150) | N |  |  |  |  |
| 5 | `domain` | varchar(150) | Y |  |  |  |  |
| 6 | `port` | int | N | 389 |  |  |  |
| 7 | `ldap_bind_dn` | varchar(255) | N |  |  |  |  |
| 8 | `ldap_bind_pw` | varchar(150) | N |  |  |  |  |
| 9 | `ldap_base_dn` | varchar(255) | N |  |  |  |  |
| 10 | `type` | varchar(255) | N |  |  |  |  |
| 11 | `ldap_auth_filter` | varchar(255) | Y | (\| (sn=%USERNAME%) ) |  |  |  |
| 12 | `ldap_auth_attribute` | varchar(150) | Y |  |  |  |  |
| 13 | `ldap_name_attribute` | varchar(150) | Y |  |  |  |  |
| 14 | `ldap_email_attribute` | varchar(150) | Y |  |  |  |  |
| 15 | `ldap_memberof_attribute` | varchar(150) | Y |  |  |  |  |
| 16 | `ldap_grouplist_filter` | varchar(150) | Y |  |  |  |  |
| 17 | `ldap_grouplist_name` | varchar(150) | Y |  |  |  |  |
| 18 | `ldap_groupmemberlist_filter` | varchar(255) | Y |  |  |  |  |
| 19 | `ldap_group_account_attribute` | varchar(150) | Y |  |  |  |  |
| 20 | `ldap_group_fetch_email_type` | varchar(150) | Y |  |  |  |  |
| 21 | `ldap_group_email_attribute` | varchar(150) | Y |  |  |  |  |
| 22 | `ldap_group_mail_domain` | varchar(150) | Y |  |  |  |  |
| 23 | `status` | int | N | 0 |  |  |  |
| 24 | `workflow_status` | int | N | 0 |  |  |  |
| 25 | `workflow_owner_id` | int | Y |  |  |  |  |
| 26 | `created` | datetime | N |  |  |  |  |
| 27 | `modified` | datetime | N |  |  |  |  |
| 28 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `account_review_feeds`.ldap_connector_id, `authentication_settings`.auth_awareness_id, `authentication_settings`.auth_policies_id, `authentication_settings`.ldap_connector_id, `awareness_programs`.ldap_connector_id, `ldap_connector_authentication`.auth_awareness_id, `ldap_connector_authentication`.auth_policies_id, `ldap_connector_authentication`.auth_users_id, `ldap_synchronizations`.ldap_auth_connector_id, `ldap_synchronizations`.ldap_group_connector_id, `security_policies`.ldap_connector_id

---

### `ldap_synchronizations`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | Y |  |  |  |  |
| 3 | `description` | text | Y |  |  |  |  |
| 4 | `ldap_auth_connector_id` | int | N |  | MUL |  | FK -> `ldap_connectors`.id |
| 5 | `ldap_group_connector_id` | int | N |  | MUL |  | FK -> `ldap_connectors`.id |
| 6 | `ldap_group` | varchar(255) | N |  |  |  |  |
| 7 | `status` | int | N | 1 |  |  |  |
| 8 | `language` | varchar(10) | N |  |  |  |  |
| 9 | `api` | int | N |  |  |  |  |
| 10 | `no_user_action` | int | N |  |  |  |  |
| 11 | `created` | datetime | N |  |  |  |  |
| 12 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `ldap_synchronizations_groups`.ldap_synchronization_id, `ldap_synchronizations_portals`.ldap_synchronization_id, `users_ldap_synchronizations`.ldap_synchronization_id

---

### `ldap_synchronizations_groups`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `ldap_synchronization_id` | int | N |  | MUL |  | FK -> `ldap_synchronizations`.id |
| 3 | `group_id` | int | N |  | MUL |  | FK -> `groups`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `ldap_synchronizations_portals`

*Rows: 0 · link/join table*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `ldap_synchronization_id` | int | N |  | MUL |  | FK -> `ldap_synchronizations`.id |
| 3 | `portal_id` | int | N |  | MUL |  | FK -> `portals`.id |
| 4 | `created` | datetime | N |  |  |  |  |
| 5 | `modified` | datetime | N |  |  |  |  |

---

### `oauth2_access_tokens`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `client_id` | int | N |  | MUL |  | FK -> `oauth2_clients`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `token_hash` | varchar(255) | N |  | UNI |  |  |
| 5 | `scope` | varchar(255) | Y |  |  |  |  |
| 6 | `resource` | varchar(255) | N |  |  |  |  |
| 7 | `expires` | datetime | N |  | MUL |  |  |
| 8 | `revoked` | datetime | Y |  |  |  |  |
| 9 | `last_used` | datetime | Y |  |  |  |  |
| 10 | `created` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `oauth2_refresh_tokens`.access_token_id

---

### `oauth2_authorization_codes`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `client_id` | int | N |  | MUL |  | FK -> `oauth2_clients`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `code_hash` | varchar(255) | N |  | UNI |  |  |
| 5 | `redirect_uri` | text | N |  |  |  |  |
| 6 | `scope` | varchar(255) | Y |  |  |  |  |
| 7 | `resource` | varchar(255) | N |  |  |  |  |
| 8 | `code_challenge` | varchar(255) | N |  |  |  |  |
| 9 | `code_challenge_method` | varchar(16) | N |  |  |  |  |
| 10 | `expires` | datetime | N |  | MUL |  |  |
| 11 | `consumed` | datetime | Y |  |  |  |  |
| 12 | `created` | datetime | Y |  |  |  |  |

---

### `oauth2_clients`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `client_id` | varchar(128) | N |  | UNI |  |  |
| 3 | `client_secret_hash` | varchar(255) | Y |  |  |  |  |
| 4 | `client_name` | varchar(255) | Y |  |  |  |  |
| 5 | `redirect_uris` | text | N |  |  |  |  |
| 6 | `grant_types` | text | Y |  |  |  |  |
| 7 | `response_types` | text | Y |  |  |  |  |
| 8 | `scope` | varchar(255) | Y |  |  |  |  |
| 9 | `token_endpoint_auth_method` | varchar(64) | N | none |  |  |  |
| 10 | `created` | datetime | Y |  |  |  |  |
| 11 | `modified` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `oauth2_access_tokens`.client_id, `oauth2_authorization_codes`.client_id, `oauth2_refresh_tokens`.client_id

---

### `oauth2_refresh_tokens`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `client_id` | int | N |  | MUL |  | FK -> `oauth2_clients`.id |
| 3 | `user_id` | int | N |  | MUL |  | FK -> `users`.id |
| 4 | `access_token_id` | int | Y |  | MUL |  | FK -> `oauth2_access_tokens`.id |
| 5 | `token_hash` | varchar(255) | N |  | UNI |  |  |
| 6 | `scope` | varchar(255) | Y |  |  |  |  |
| 7 | `resource` | varchar(255) | N |  |  |  |  |
| 8 | `expires` | datetime | N |  | MUL |  |  |
| 9 | `revoked` | datetime | Y |  |  |  |  |
| 10 | `used` | datetime | Y |  |  |  |  |
| 11 | `replaced_by_token_id` | int | Y |  | MUL |  | FK -> `oauth2_refresh_tokens`.id |
| 12 | `created` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `oauth2_refresh_tokens`.replaced_by_token_id

---

### `oauth_connectors`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `client_id` | varchar(255) | N |  |  |  |  |
| 4 | `client_secret` | varchar(255) | N |  |  |  |  |
| 5 | `provider` | varchar(255) | N |  |  |  |  |
| 6 | `status` | int | N | 1 |  |  |  |
| 7 | `created` | datetime | N |  |  |  |  |
| 8 | `modified` | datetime | N |  |  |  |  |
| 9 | `edited` | datetime | Y |  |  |  |  |

**Referenced by (FK):** `authentication_settings`.oauth_connector_id

---

### `request_tokens`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `token` | varchar(128) | N |  |  |  |  |
| 3 | `consumed` | tinyint(1) | N | 0 |  |  |  |
| 4 | `expires` | datetime | N |  |  |  |  |
| 5 | `created` | datetime | N |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |

---

### `saml_connectors`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `name` | varchar(255) | N |  |  |  |  |
| 3 | `identity_provider` | varchar(255) | N |  |  |  |  |
| 4 | `idp_certificate` | text | N |  |  |  |  |
| 5 | `remote_sign_in_url` | varchar(255) | N |  |  |  |  |
| 6 | `remote_sign_out_url` | varchar(255) | N |  |  |  |  |
| 7 | `email_field` | varchar(255) | N |  |  |  |  |
| 8 | `sign_saml_request` | int | N | 0 |  |  |  |
| 9 | `sp_certificate` | text | N |  |  |  |  |
| 10 | `sp_private_key` | text | N |  |  |  |  |
| 11 | `authentication_context` | varchar(255) | N | urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport |  |  |  |
| 12 | `validate_saml_request` | int | N | 1 |  |  |  |
| 13 | `status` | int | N | 1 |  |  |  |
| 14 | `created` | datetime | N |  |  |  |  |
| 15 | `modified` | datetime | N |  |  |  |  |

**Referenced by (FK):** `authentication_settings`.saml_connector_id, `ldap_connector_authentication`.saml_connector_id

---

### `tickets`

*Rows: 2*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `is_used` | tinyint(1) | N | 0 |  |  |  |
| 3 | `hash` | varchar(50) | Y |  | UNI |  |  |
| 4 | `data` | varchar(50) | Y |  |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |
| 6 | `modified` | datetime | N |  |  |  |  |
| 7 | `expires` | datetime | Y |  |  |  |  |

---

### `user_tokens`

*Rows: 0*

| # | Column | Type | Null | Default | Key | Extra | Maps to |
|--:|--------|------|:----:|---------|:---:|-------|---------|
| 1 | `id` | int | N |  | PRI | auto_increment |  |
| 2 | `user_id` | int | Y |  | MUL |  | FK -> `users`.id |
| 3 | `token_hash` | varchar(255) | Y |  |  |  |  |
| 4 | `expires` | datetime | Y |  |  |  |  |
| 5 | `created` | datetime | Y |  |  |  |  |

---
