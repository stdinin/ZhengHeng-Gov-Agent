from enum import StrEnum

from fastapi import HTTPException


class Role(StrEnum):
    USER = "USER"
    DEPT_ADMIN = "DEPT_ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


_ROLE_RANK = {Role.USER: 0, Role.DEPT_ADMIN: 1, Role.SUPER_ADMIN: 2}


def ensure_role(actual: Role, required: Role) -> None:
    if _ROLE_RANK[actual] < _ROLE_RANK[required]:
        raise HTTPException(status_code=403, detail="Insufficient role for this operation.")
