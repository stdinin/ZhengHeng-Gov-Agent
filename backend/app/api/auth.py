from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.security.auth import create_access_token, decode_access_token, verify_password
from backend.app.security.rbac import Role
from backend.app.storage.users import UserStore

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PublicUser(BaseModel):
    id: str
    email: str
    role: Role


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PublicUser


def _store(request: Request) -> UserStore:
    return cast(UserStore, request.app.state.user_store)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request) -> LoginResponse:
    user = await _store(request).get_by_email(payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="The email or password is invalid.",
        )
    settings: Settings = request.app.state.settings
    return LoginResponse(
        access_token=create_access_token(user, settings),
        user=PublicUser(id=user.id, email=user.email, role=user.role),
    )


@router.get("/me", response_model=PublicUser)
async def me(request: Request) -> PublicUser:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="Bearer token is required.")
    try:
        user_id = decode_access_token(token, request.app.state.settings)
    except ValueError as error:
        raise ApiError(status_code=401, code="INVALID_TOKEN", message=str(error)) from error
    user = await _store(request).get_by_id(user_id)
    if user is None:
        raise ApiError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Token user no longer exists.",
        )
    return PublicUser(id=user.id, email=user.email, role=user.role)
