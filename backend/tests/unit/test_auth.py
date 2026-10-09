import httpx

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.security.auth import User, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore

TEST_APP_SECRET = "test-secret-that-is-at-least-32-bytes"


async def test_login_returns_bearer_token_for_seeded_local_user() -> None:
    users = InMemoryUserStore(
        [
            User(
                id="user_demo",
                email="user@example.local",
                password_hash=hash_password("demo-user"),
                role=Role.USER,
            )
        ]
    )
    app = create_app(settings=Settings(app_secret=TEST_APP_SECRET), user_store=users)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.local", "password": "demo-user"},
        )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"


async def test_login_rejects_an_invalid_password() -> None:
    users = InMemoryUserStore(
        [
            User(
                id="user_demo",
                email="user@example.local",
                password_hash=hash_password("demo-user"),
                role=Role.USER,
            )
        ]
    )
    app = create_app(settings=Settings(app_secret=TEST_APP_SECRET), user_store=users)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.local", "password": "incorrect"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
