from pydantic import BaseModel

from suite.ai_control_plane.models import TenantPolicy, UserContext
from suite.platform.runtime import is_production_environment, suite_auth_mode


class DevHeaderAuthError(ValueError):
    pass


class TenantRequestContext(BaseModel):
    user_context: UserContext
    tenant_policy: TenantPolicy


def require_dev_header_auth_allowed() -> None:
    if suite_auth_mode() != "dev":
        raise DevHeaderAuthError("Dev header tenant context requires SUITE_AUTH_MODE=dev")
    if is_production_environment():
        raise DevHeaderAuthError("Dev header tenant context is disabled in production")
