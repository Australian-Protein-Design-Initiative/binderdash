# Authentication Setup

Binderdash supports five authentication modes:

- Auth disabled (public API)
- Session auth via local bcrypt users
- Session auth via PAM (Unix accounts)
- Session auth via Google OAuth (OIDC)
- Per-user API key auth for scripted access

You can enable multiple auth providers at the same time.

## Quick Reference

- `DISABLE_AUTHENTICATION="true"` makes all protected endpoints public and bypasses provider checks.
- Session auth uses cookies (`binderdash_session`) and CSRF protection for non-GET requests.
- API key auth uses `Authorization: Bearer <key>` or `X-Binderdash-Api-Key: <key>`. Keys are per-user, named, expiring, and revocable (there is no shared server secret) and require `DATABASE`.
- Username/password login (`POST /api/auth/login`) checks local users first, then PAM (if enabled).
- Google OAuth signs in through `/api/auth/google/login` and creates the same session cookies as local/PAM login.
- Every successful login resolves to a user (see [User model and admin allowlist](#user-model-and-admin-allowlist)); `BINDERDASH_ADMIN_USERS` is re-applied on every startup and login.

## Environment Variables

Auth-related variables supported in `.env.example`:

- `DISABLE_AUTHENTICATION`
- `LOCAL_USERS`
- `PAM_LOCAL_ENABLED`
- `PAM_LOCAL_ALLOWED_USERS`
- `PAM_LOCAL_SERVICE`
- `PAM_GECOS_EMAIL`
- `GOOGLE_AUTH_ENABLED`
- `GOOGLE_AUTH_CLIENT_ID`
- `GOOGLE_AUTH_CLIENT_SECRET`
- `GOOGLE_AUTH_REDIRECT_URI`
- `GOOGLE_AUTH_ALLOWED_USERS`
- `SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `BINDERDASH_ADMIN_USERS`
- `DATABASE` (required for per-user API keys)

## Provider Precedence and Coexistence

When multiple options are enabled:

1. Global override: if `DISABLE_AUTHENTICATION="true"`, auth is bypassed for protected routes.
2. Protected API route auth (when auth is enabled):
   - API key is checked first.
   - If no valid API key is present, session cookie auth is checked.
3. Username/password login flow (`POST /api/auth/login`):
   - Local bcrypt users are checked first.
   - PAM is checked only if local auth did not match and `PAM_LOCAL_ENABLED="true"`.
4. Google OAuth flow:
   - Independent login path that issues session cookies on success.
   - Protected routes then follow the API key and cookie precedence above.

## Auth Type 1: Disable Authentication (Public Mode)

Use this for local development only.

```bash
DISABLE_AUTHENTICATION="true"
```

Notes:

- Protected endpoints no longer require login, API key, or CSRF.
- You can leave other auth variables set; they are effectively bypassed while this is `true`.

## Auth Type 2: Local Username/Password (bcrypt)

Enable local session login with bcrypt hashes in `LOCAL_USERS`.

### Step 1: Generate bcrypt hashes

```bash
python backend/scripts/encrypt_password.py alice
python backend/scripts/encrypt_password.py bob
```

### Step 2: Set `LOCAL_USERS`

```bash
LOCAL_USERS="alice:$2b$12$...,bob:$2b$12$..."
DISABLE_AUTHENTICATION="false"
```

### Step 3: Login

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "alice",
  "password": "your-password"
}
```

Successful login returns user details plus `csrf_token`, and sets session cookies.

## Auth Type 3: PAM Username/Password (Unix Accounts)

Enable PAM-based login for allowed system users.

```bash
PAM_LOCAL_ENABLED="true"
PAM_LOCAL_ALLOWED_USERS="ubuntu,bob,alice"   # comma-separated list, or "*" for any PAM-valid user
PAM_LOCAL_SERVICE="common-auth"
DISABLE_AUTHENTICATION="false"
```

Important:

- PAM login is attempted only after local user auth fails.
- `PAM_LOCAL_ALLOWED_USERS` is required in practice (`*` or a comma-separated allowlist; case-insensitive).
- In containers, host users usually do not exist unless explicitly provided.

### PAM with Docker Compose (required host account binds)

When Binderdash runs in Docker, PAM checks the container's user database by default.  
That usually includes only container users (for example `app`), not host users like `perry`.

To authenticate host Linux users through PAM in Docker, you must bind host account files read-only:

```yaml
services:
  binderdash:
    volumes:
      - /etc/passwd:/etc/passwd:ro
      - /etc/group:/etc/group:ro
      - /etc/shadow:/etc/shadow:ro
    group_add:
      - "42"          # gid `shadow` - see below; without it every login fails
```

The mounts are active in `docker-compose.dev.yml` and commented out in `docker-compose.yml`.

#### Requiring the `shadow` group

`pam_unix` delegates `/etc/shadow` lookups to `/sbin/unix_chkpwd`. Although that helper is setgid `shadow`, it only uses that privilege when checking the calling user's own password, preventing unprivileged processes from brute-forcing other accounts. Because the container runs as a non-root `user:`, every login for another account is a cross-user check, and `/sbin/unix_chkpwd` returns `PAM_AUTHINFO_UNAVAIL`. `pam_unix` reports this as a standard authentication error (*"Incorrect username or password"*), even with a valid password.

Adding gid `42` grants the container process direct read access to `/etc/shadow`. To diagnose the failure inside the container, run the helper directly:

```bash
docker compose exec binderdash sh -c 'printf %s "$PW" | /sbin/unix_chkpwd someuser nullok; echo $?'
# 9 = cannot read /etc/shadow (missing shadow group)
# 7 = read it fine, password genuinely wrong
```

#### Recreating the container after host account changes

Single-file bind mounts attach to the original file's inode. Because `passwd(1)` replaces `/etc/shadow` with a new file instead of editing it in place, a running container continues reading the old version. Password updates and new host users will not appear in the container, and logins will check against stale hashes. Running `docker compose restart` keeps the same container and mounts, so it will not reload the file. Compare `md5sum /etc/shadow` on the host and inside the container to verify, then recreate the container:

```bash
docker compose up -d --force-recreate
```

Recommended matching env:

```bash
PAM_LOCAL_ENABLED="true"
PAM_LOCAL_ALLOWED_USERS="bob,alice"   # comma-separated list, or "*" for broader access
PAM_LOCAL_SERVICE="common-auth"
DISABLE_AUTHENTICATION="false"
```

After changing compose mounts or env values, recreate the container so PAM sees the updated runtime:

```bash
docker compose up -d --build
```

Security note:

- Mounting `/etc/shadow` into a container exposes password-hash data to that container.
- Use this only on trusted development hosts, with minimal container access.
- For safer container auth in many cases, prefer `LOCAL_USERS` (bcrypt) instead of PAM.

## Auth Type 4: Google OAuth (OIDC)

Enable Google sign-in and restrict it to allowed emails.

### Step 1: Configure Google credentials

```bash
GOOGLE_AUTH_ENABLED="true"
GOOGLE_AUTH_CLIENT_ID="..."
GOOGLE_AUTH_CLIENT_SECRET="..."
GOOGLE_AUTH_REDIRECT_URI="http://localhost:8000/api/auth/google/callback"
GOOGLE_AUTH_ALLOWED_USERS="user1@example.com,user2@example.com"
DISABLE_AUTHENTICATION="false"
```

### Step 2: Configure redirect URI in Google Cloud

Your Google OAuth client must include the same callback URI as `GOOGLE_AUTH_REDIRECT_URI`.

### Step 3: Start login flow

Open:

```text
/api/auth/google/login
```

Notes:

- Google auth is considered configured only when enabled and client ID/secret/redirect URI are all non-empty.
- If `GOOGLE_AUTH_ALLOWED_USERS` is empty, Google sign-in is effectively denied for everyone.
- Successful callback issues the same session cookies as local/PAM login.

## Auth Type 5: Per-User API Key

Use this for scripts/agents without browser session or CSRF handling.

Per-user API keys are enabled automatically whenever `DATABASE` is configured (no separate feature flag is required):

```bash
DATABASE="sqlite:///./binderdash.db"   # or Postgres URL; keys are stored in the DB
DISABLE_AUTHENTICATION="false"
```

Create a user and an API key in the web UI (top-right account menu, **API keys**) or via the CLI:

```bash
python -m backend.cli user create --email you@example.org --admin
python -m backend.cli key create you@example.org --name bootstrap
```

The CLI writes the token to stdout and prints a warning to stderr. The raw token is displayed **once** because the server stores only its SHA-256 hash. Other CLI subcommands include `user list|show|link-identity|set-admin` and `key list|revoke`.

Use either header format:

```http
Authorization: Bearer <token>
```

or

```http
X-Binderdash-Api-Key: <token>
```

Notes:

- For state-changing requests, API key auth bypasses CSRF checks.
- On protected routes, a valid API key is accepted before cookie auth.
- `/api/auth/me` requires cookie session auth (it does not accept API key auth).
- Each key has a name, an optional expiry (`--expires-days`), and can be revoked immediately with `key revoke <id>`.
- With no `DATABASE` configured, `GET /api/auth/status` reports `api_keys.enabled: false, reason: "persistence_disabled"` and the key-management endpoints return `503`.
- Key management requires a browser session. `GET/POST /api/api-keys` and `PATCH/DELETE /api/api-keys/{id}` return `403` for API-key-authenticated requests so a compromised key cannot create replacements or list other keys. `GET /api/users` also requires admin privileges.

## User model and admin allowlist

A user represents one person, and an identity represents one login method keyed by `(provider, identifier)` (for example, `local:alice`, `pam:alice`, or `google:alice@example.org`). Binderdash creates a user automatically on the first successful login. Two identities merge into the same user only when they share a verified email address. For example, PAM login for `alice` and Google login for `alice@example.org` merge only when `PAM_GECOS_EMAIL` resolves to the same address (see below); otherwise they remain separate users.

`BINDERDASH_ADMIN_USERS` is a comma-separated allowlist that grants `is_admin`. Entries match a user's email, `provider:identifier` pair, or plain username. Unlike `PAM_LOCAL_ALLOWED_USERS`, this variable does not support a `*` wildcard, preventing accidental admin grants to all users. Binderdash re-applies this allowlist on every startup and login. To revoke admin access, remove the entry and restart or wait for the user's next login. Admin status granted via `python -m backend.cli user set-admin` will be overwritten unless the user is also listed in `BINDERDASH_ADMIN_USERS`.

### `PAM_GECOS_EMAIL`

Default: `false`. When `true`, PAM login reads the user's email from the **5th GECOS field only** ("other") and ignores fields 1-4 ("full name", "room", "work phone", "home phone").

Restricting to the 5th field prevents account takeover. Standard Linux configurations set `CHFN_RESTRICT="rwh"` in `/etc/login.defs`, allowing local users to edit their room, work phone, and home phone via `chfn`. Because `chfn` has no flag for the 5th field and rejects commas in input, only root can set that field. Reading any user-writable field would allow a shell user to enter another user's email with `chfn`, merge into that Binderdash account, and gain access to its API keys and admin privileges.

## Session and CSRF Behaviour

When auth is enabled and you use session cookies:

- Server sets:
  - `binderdash_session` (HttpOnly session token)
  - `binderdash_csrf` (readable cookie)
- For non-GET/HEAD/OPTIONS requests, send `X-CSRF-Token` matching `binderdash_csrf`.

CSRF checks are skipped for:

- `/api/auth/login`
- `/api/auth/logout`
- `/api/auth/status`
- `/api/auth/google/login`
- `/api/auth/google/callback`
- Any request with a valid API key

## Verify Active Providers

Use:

```http
GET /api/auth/status
```

Response shape:

```json
{
  "auth_disabled": false,
  "desktop_mode": false,
  "providers": {
    "local": { "enabled": true },
    "pam": { "enabled": false },
    "google": { "enabled": true, "login_url": "/api/auth/google/login" }
  },
  "api_keys": { "enabled": true, "reason": null }
}
```

`api_keys.reason` is `null` when keys are enabled, `"auth_disabled"` when `DISABLE_AUTHENTICATION=true` (keys require user accounts), or `"persistence_disabled"` when `DATABASE` is unset.

## Recommended Combinations

- Local dev (public): `DISABLE_AUTHENTICATION="true"`
- Team dev (session login): local users and/or PAM, `DISABLE_AUTHENTICATION="false"`
- Production user login: Google OAuth + allowlist, `DISABLE_AUTHENTICATION="false"`
- Automation access: configure `DATABASE`, then create per-user keys via the UI or `python -m backend.cli key create` (works alongside any session provider)
