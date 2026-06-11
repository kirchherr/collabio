import os

PRODUCTION_ENVIRONMENTS = {"prod", "production"}


def suite_env() -> str:
    return os.getenv("SUITE_ENV", "dev").strip().lower()


def suite_auth_mode() -> str:
    return os.getenv("SUITE_AUTH_MODE", "dev").strip().lower()


def is_production_environment() -> bool:
    return suite_env() in PRODUCTION_ENVIRONMENTS
