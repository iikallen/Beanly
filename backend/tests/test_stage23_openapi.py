from beanly.main import app


def test_onboarding_openapi_surface_and_verbs_are_frozen() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/onboarding/status": "get",
        "/api/v1/onboarding/bootstrap": "post",
        "/api/v1/onboarding/capabilities": "get",
        "/api/v1/onboarding/templates": "get",
        "/api/v1/onboarding/templates/spreadsheet": "get",
        "/api/v1/onboarding/templates/{code}/preview": "post",
        "/api/v1/onboarding/imports": "get",
        "/api/v1/onboarding/imports/inspect": "post",
        "/api/v1/onboarding/imports/{run_id}": "get",
        "/api/v1/onboarding/imports/{run_id}/entities/{entity_id}": "patch",
        "/api/v1/onboarding/imports/{run_id}/validate": "post",
        "/api/v1/onboarding/imports/{run_id}/apply": "post",
        "/api/v1/onboarding/imports/{run_id}/cancel": "post",
        "/api/v1/onboarding/imports/{run_id}/resume": "post",
        "/api/v1/onboarding/imports/{run_id}/prices": "put",
        "/api/v1/onboarding/imports/{run_id}/activate-ready": "post",
    }
    for path, verb in expected.items():
        assert verb in paths[path]
    assert "post" in paths["/api/v1/onboarding/imports"]


def test_upload_contract_accepts_and_persists_generic_mapping() -> None:
    schemas = app.openapi()["components"]["schemas"]
    body = schemas["Body_upload_import_api_v1_onboarding_imports_post"]
    assert "mapping_json" in body["properties"]


def test_bootstrap_created_flags_are_both_required() -> None:
    schema = app.openapi()["components"]["schemas"]["BootstrapCreatedResponse"]
    assert set(schema["required"]) == {"warehouse", "register"}
