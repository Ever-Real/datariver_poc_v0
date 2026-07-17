from datariver.interfaces.http.routes.auth import _roles


def test_auth_me_filters_and_sorts_only_string_realm_roles() -> None:
    assert _roles({"roles": ["viewer", "admin", "viewer", 1, " "]}) == ["admin", "viewer"]
    assert _roles({"roles": "admin"}) == []
    assert _roles(None) == []
