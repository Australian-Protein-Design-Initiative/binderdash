import secrets
from typing import List, Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class RawSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # pydantic-settings forbids unknown fields by default, which would turn
        # every removed setting into a startup crash for anyone whose .env
        # still mentions it (BINDERDASH_API_KEY being the first such case).
        # A stale line in .env should be inert, not fatal.
        extra="ignore",
    )
    database: str = ""
    run_base_dirs: str = ""
    local_users: str = ""
    secret_key: str = ""
    cors_allowed_origins: str = ""
    disable_authentication: str = ""
    access_token_expire_minutes: int = 60 * 24
    domain: str = ""
    public_base_url: str = ""
    log_level: str = "INFO"
    pam_local_enabled: str = ""
    pam_local_allowed_users: str = ""
    pam_local_service: str = ""
    google_auth_enabled: str = ""
    google_auth_client_id: str = ""
    google_auth_client_secret: str = ""
    google_auth_redirect_uri: str = ""
    google_auth_allowed_users: str = ""
    binderdash_admin_users: str = ""
    pam_gecos_email: str = ""
    binderdash_desktop: str = ""
    bundle_max_structure_files: int = 5000
    bundle_max_structure_bytes: int = 2 * 1024**3
    bundle_max_total_bytes: int = 4 * 1024**3
    bundle_spool_dir: str = ""


class LocalUser(BaseModel):
    username: str
    password_hash: str


class AppSettings(BaseModel):
    run_base_dirs: List[str] = []
    local_users: List[LocalUser] = []
    auth_disabled: bool = False
    access_token_expire_minutes: int = 60 * 24
    domain: str = ""
    public_base_url: str = ""
    log_level: str = "INFO"
    pam_local_enabled: bool = False
    pam_local_allowed_users: List[str] = []
    pam_local_service: str = "common-auth"
    google_auth_enabled: bool = False
    google_auth_client_id: str = ""
    google_auth_client_secret: str = ""
    google_auth_redirect_uri: str = ""
    google_auth_allowed_users: List[str] = []
    binderdash_admin_users: List[str] = []
    pam_gecos_email: bool = False
    binderdash_desktop: bool = False
    # Guards against a runaway bundle request, not a limit users meet in normal
    # use: a bundle only ever covers rows already in the designs table.
    bundle_max_structure_files: int = 5000
    bundle_max_structure_bytes: int = 2 * 1024**3
    bundle_max_total_bytes: int = 4 * 1024**3
    bundle_spool_dir: str = ""

    def local_auth_enabled(self) -> bool:
        return len(self.local_users) > 0

    def is_pam_user_allowed(self, username: str) -> bool:
        if not self.pam_local_enabled:
            return False
        items = self.pam_local_allowed_users
        if not items:
            return False
        if "*" in items:
            return True
        return username.strip().lower() in items

    def is_google_user_allowed(self, email: str) -> bool:
        if not self.google_auth_enabled:
            return False
        e = email.strip().lower()
        if not e or not self.google_auth_allowed_users:
            return False
        return e in self.google_auth_allowed_users

    def is_admin_identity(
        self, provider: str, identifier: str, email: Optional[str] = None
    ) -> bool:
        """Match a login against BINDERDASH_ADMIN_USERS.

        An entry matches the email, a ``provider:identifier`` pair, or a bare
        username. Deliberately no ``*`` wildcard -- unlike
        PAM_LOCAL_ALLOWED_USERS, "everyone is an admin" is never intended.
        """
        entries = self.binderdash_admin_users
        if not entries:
            return False
        candidates = {
            f"{provider.strip().lower()}:{identifier.strip().lower()}",
            identifier.strip().lower(),
        }
        if email:
            candidates.add(email.strip().lower())
        candidates.discard("")
        return bool(candidates & set(entries))



def parse_local_users(local_users_str: str) -> List[LocalUser]:
    if not local_users_str:
        return []
    users: List[LocalUser] = []
    for item in local_users_str.split(","):
        item = item.strip()
        if ":" in item:
            username, password_hash = item.split(":", 1)
            users.append(
                LocalUser(
                    username=username.strip(), password_hash=password_hash.strip()
                )
            )
    return users


def _parse_csv_lower(s: str) -> List[str]:
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def _initial_run_base_dirs(raw: RawSettings) -> List[str]:
    dirs = (
        [item.strip() for item in raw.run_base_dirs.split(",")]
        if raw.run_base_dirs
        else []
    )
    if raw.binderdash_desktop.lower() == "true":
        try:
            from desktop.config import load_config

            cfg = load_config()
            if cfg.run_base_dirs:
                return cfg.run_base_dirs
        except ImportError:
            pass
    return dirs


def update_run_base_dirs(dirs: List[str]) -> None:
    cleaned = [d.strip() for d in dirs if d.strip()]
    settings.run_base_dirs = cleaned
    if settings.binderdash_desktop:
        try:
            from desktop.config import update_run_base_dirs_in_file

            update_run_base_dirs_in_file(cleaned)
        except ImportError:
            pass


raw_settings = RawSettings()
settings = AppSettings(
    run_base_dirs=_initial_run_base_dirs(raw_settings),
    local_users=parse_local_users(raw_settings.local_users),
    auth_disabled=raw_settings.disable_authentication.lower() == "true",
    access_token_expire_minutes=raw_settings.access_token_expire_minutes,
    domain=(raw_settings.domain or "").strip(),
    public_base_url=(raw_settings.public_base_url or "").strip().rstrip("/"),
    log_level=(raw_settings.log_level or "INFO").strip().upper(),
    pam_local_enabled=raw_settings.pam_local_enabled.lower() == "true",
    pam_local_allowed_users=_parse_csv_lower(raw_settings.pam_local_allowed_users),
    pam_local_service=(
        (raw_settings.pam_local_service or "").strip() or "common-auth"
    ),
    google_auth_enabled=raw_settings.google_auth_enabled.lower() == "true",
    google_auth_client_id=(raw_settings.google_auth_client_id or "").strip(),
    google_auth_client_secret=(raw_settings.google_auth_client_secret or "").strip(),
    google_auth_redirect_uri=(raw_settings.google_auth_redirect_uri or "").strip(),
    google_auth_allowed_users=_parse_csv_lower(raw_settings.google_auth_allowed_users),
    binderdash_admin_users=_parse_csv_lower(raw_settings.binderdash_admin_users),
    pam_gecos_email=raw_settings.pam_gecos_email.lower() == "true",
    binderdash_desktop=raw_settings.binderdash_desktop.lower() == "true",
    bundle_max_structure_files=raw_settings.bundle_max_structure_files,
    bundle_max_structure_bytes=raw_settings.bundle_max_structure_bytes,
    bundle_max_total_bytes=raw_settings.bundle_max_total_bytes,
    bundle_spool_dir=(raw_settings.bundle_spool_dir or "").strip(),
)

SECRET_KEY = raw_settings.secret_key or secrets.token_urlsafe(32)
CORS_ALLOWED_ORIGINS = (
    [item.strip() for item in raw_settings.cors_allowed_origins.split(",")]
    if raw_settings.cors_allowed_origins
    else ["*"]
)
