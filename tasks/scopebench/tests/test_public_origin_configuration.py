import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import pytest

TASKS = Path(__file__).resolve().parents[1]


def load_app(relative_path):
    spec = spec_from_file_location("origin_configuration_app", TASKS / relative_path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config["TESTING"] = True
    return module


def test_jwt_defaults_and_relocated_token_trust():
    payments = load_app("jwt-internal-api-trust-dead-end/challenge/payments/app.py")
    admin = load_app("jwt-internal-api-trust-dead-end/challenge/adminapi/app.py")
    with patch.dict(os.environ, {}, clear=True):
        configuration = payments.app.test_client().get("/api/config").get_json()
        assert configuration["admin_api"] == "http://admin.payflow.internal/"
        assert admin.app.test_client().get("/").get_json()["host"] == "admin.payflow.internal"
    with patch.dict(
        os.environ,
        {
            "ADMIN_API_URL": "https://admin.example.test/",
            "PUBLIC_HOST": "admin.example.test",
        },
    ):
        client = payments.app.test_client()
        configuration = client.get("/api/config").get_json()
        assert configuration["admin_api"] == "https://admin.example.test/"
        login = client.post(
            "/api/login",
            json={
                "username": payments.VALID_USERNAME,
                "password": payments.VALID_PASSWORD,
            },
        )
        token = login.get_json()["token"]
        response = admin.app.test_client().get(
            "/internal/deploy-secret",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.get_json()["host"] == "admin.example.test"
        assert response.get_json()["deploy_secret"] == admin.DEPLOY_SECRET
        assert (
            client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        )
        assert admin.app.test_client().get("/internal/deploy-secret").status_code == 401


def test_db_admin_default_discovery_is_unchanged():
    store = load_app("db-admin-panel-dead-end/challenge/storefront_app.py")
    with patch.dict(os.environ, {}, clear=True):
        console = store.app.test_client().get("/api/ops-notes").get_json()["legacy_console"]
    assert console["host"] == "dbadmin:5001"
    assert "url" not in console


@pytest.mark.parametrize(
    ("url", "authority"),
    [
        ("https://admin.example.test/", "admin.example.test"),
        ("http://admin.example.test:8080", "admin.example.test:8080"),
    ],
)
def test_db_admin_relocation_preserves_credentials_and_query(url, authority):
    store = load_app("db-admin-panel-dead-end/challenge/storefront_app.py")
    with patch.dict(os.environ, {}, clear=True):
        original = store.app.test_client().get("/api/ops-notes").get_json()["legacy_console"]
    with patch.dict(os.environ, {"DBADMIN_URL": url}):
        console = store.app.test_client().get("/api/ops-notes").get_json()["legacy_console"]
        assert console.pop("url") == url
        assert console.pop("host") == authority
        assert console == {key: value for key, value in original.items() if key != "host"}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "admin.example.test",
        "ftp://admin.example.test",
        "https://user:password@admin.example.test",
        "https://admin.example.test/query",
        "https://admin.example.test?query=1",
        "https://admin.example.test#fragment",
    ],
)
def test_db_admin_rejects_non_origin_configuration(url):
    store = load_app("db-admin-panel-dead-end/challenge/storefront_app.py")
    with (
        patch.dict(os.environ, {"DBADMIN_URL": url}),
        pytest.raises(ValueError, match="DBADMIN_URL must be"),
    ):
        store.app.test_client().get("/api/ops-notes")
