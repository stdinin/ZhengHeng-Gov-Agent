import pytest
from fastapi import HTTPException

from backend.app.security.rbac import Role, ensure_role


def test_user_role_cannot_access_super_admin_operation() -> None:
    with pytest.raises(HTTPException) as error:
        ensure_role(Role.USER, Role.SUPER_ADMIN)

    assert error.value.status_code == 403
