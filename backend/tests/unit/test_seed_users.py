from scripts.seed_users import demo_users


def test_demo_users_expose_only_the_documented_local_accounts() -> None:
    users = demo_users()

    assert [(user.email, user.role.value) for user in users] == [
        ("user@example.local", "USER"),
        ("admin@example.local", "DEPT_ADMIN"),
        ("root@example.local", "SUPER_ADMIN"),
    ]
