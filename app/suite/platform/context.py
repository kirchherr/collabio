from pydantic import BaseModel

from suite.ai_control_plane.models import TenantPolicy, UserContext


class TenantRequestContext(BaseModel):
    user_context: UserContext
    tenant_policy: TenantPolicy
