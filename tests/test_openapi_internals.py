"""Focused tests for internal OpenAPI scaffolding helpers."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mcpme._openapi import (
    _annotation_from_schema,
    _collect_parameters,
    _dedupe_name,
    _default_base_url,
    _fallback_operation_name,
    _OpenApiOperation,
    _OpenApiParameter,
    _operation_body_lines,
    _operation_docstring_lines,
    _operation_signature_lines,
    _operation_url_lines,
    _parameter_from_spec,
    _preferred_content_type,
    _render_openapi_facade,
    _render_operation,
    _resolve_mapping_reference,
    _resolve_schema,
    _sanitize_name,
    scaffold_openapi,
)


def test_scaffold_openapi_rejects_invalid_top_level_shapes(tmp_path: Path) -> None:
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text('{"paths": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        scaffold_openapi(bad_spec, tmp_path / "out.py")

    bad_paths = tmp_path / "bad_paths.json"
    bad_paths.write_text('{"openapi": "3.1.0", "paths": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        scaffold_openapi(bad_paths, tmp_path / "out_paths.py")


def test_scaffold_openapi_tracks_skipped_path_and_operation_shapes(tmp_path: Path) -> None:
    spec = tmp_path / "skips.json"
    spec.write_text(
        (
            '{"openapi": "3.1.0", "paths": {'
            '"bad_path": 3,'
            '"/ok": {"get": 5, "post": {"operationId": "valid"}}'
            "}}"
        ),
        encoding="utf-8",
    )

    report = scaffold_openapi(spec, tmp_path / "out.py")

    reasons = {entry.reason for entry in report.skipped}
    assert "path item is not a mapping" in reasons
    assert "operation object is not a mapping" in reasons
    assert {tool.name for tool in report.generated_tools} == {"valid"}


def test_openapi_helper_functions_cover_reference_and_schema_edges() -> None:
    document = {
        "components": {
            "parameters": {
                "CaseId": {
                    "name": "case-id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            },
            "schemas": {"Case": {"type": "object"}},
        },
        "servers": [{"url": "https://api.example.com"}, {"url": "{templated}"}],
    }

    assert _default_base_url(document) == "https://api.example.com"
    assert _default_base_url({"servers": "oops"}) is None
    assert _collect_parameters(document, "oops") == {}
    assert (
        _resolve_mapping_reference(
            document,
            {"$ref": "#/components/parameters/CaseId"},
        )
        == document["components"]["parameters"]["CaseId"]
    )
    assert _resolve_schema(document, {"$ref": "#/components/schemas/Case"}) == {"type": "object"}

    with pytest.raises(ValueError):
        _resolve_mapping_reference(document, {"$ref": "https://example.com/ref"})
    with pytest.raises(ValueError):
        _resolve_mapping_reference(document, {"$ref": "#/components/parameters/Missing"})

    used_names = {"headers"}
    parameter = _parameter_from_spec(
        document,
        {
            "name": "headers",
            "in": "query",
            "schema": {"type": "integer"},
        },
        used_names=used_names,
    )
    assert parameter is not None
    assert parameter.name == "query_headers"
    assert parameter.description == "Query parameter headers."

    assert _parameter_from_spec(document, {"name": 4, "in": "query"}, used_names=set()) is None
    with pytest.raises(ValueError):
        _parameter_from_spec(
            document,
            {"name": "!!!", "in": "query", "schema": {"type": "string"}},
            used_names=set(),
        )

    assert _preferred_content_type({"content": {"text/plain": {}, "application/xml": {}}}) == (
        "text/plain"
    )
    assert _preferred_content_type({"content": {"application/xml": {}}}) == "application/xml"
    assert _preferred_content_type({"content": {}}) is None
    assert _preferred_content_type({"content": "oops"}) is None

    assert _annotation_from_schema({"type": "string"}) == "str"
    assert _annotation_from_schema({"type": "integer"}) == "int"
    assert _annotation_from_schema({"type": "number"}) == "float"
    assert _annotation_from_schema({"type": "boolean"}) == "bool"
    assert _annotation_from_schema({"type": "array"}) == "list[Any]"
    assert _annotation_from_schema({"type": "object"}) == "dict[str, Any]"
    assert _annotation_from_schema({}) == "Any"

    assert _fallback_operation_name("get", "/cases/{case_id}") == "get_cases_case_id"
    assert _sanitize_name("X-Mode!") == "x_mode"
    assert _dedupe_name("case", {"case"}) == "case_2"


def test_openapi_render_helpers_cover_cookie_body_and_docstring_paths() -> None:
    operation = _OpenApiOperation(
        name="get_case",
        method="get",
        path="/cases/{case_id}",
        summary="Fetch case",
        description="Fetch case",
        parameters=(
            _OpenApiParameter(
                name="case_id",
                original_name="case_id",
                location="path",
                annotation_source="str",
                required=True,
                description="Case id.",
            ),
            _OpenApiParameter(
                name="verbose",
                original_name="verbose",
                location="query",
                annotation_source="bool",
                required=False,
                description="Verbose query.",
            ),
            _OpenApiParameter(
                name="x_mode",
                original_name="X-Mode",
                location="header",
                annotation_source="str",
                required=False,
                description="Mode header.",
            ),
            _OpenApiParameter(
                name="session_cookie",
                original_name="session",
                location="cookie",
                annotation_source="str",
                required=False,
                description="Session cookie.",
            ),
        ),
        body_required=False,
        body_description="Body payload.",
        body_content_type="text/plain",
    )

    signature_lines = _operation_signature_lines(operation)
    assert "    case_id: str," in signature_lines
    assert "    body: Any | None = None," in signature_lines
    assert "    headers: dict[str, str] | None = None," in signature_lines

    docstring_lines = _operation_docstring_lines(operation)
    assert "    :param body: Body payload." in docstring_lines

    url_lines = _operation_url_lines(operation)
    assert "    query = _encode_query({" in url_lines
    assert "        request_headers.setdefault('Cookie', '; '.join(cookie_parts))" in url_lines

    body_lines = _operation_body_lines(operation)
    assert "    request_content_type = 'text/plain'" in body_lines

    rendered_operation = _render_operation(operation)
    assert "    request_headers = dict(headers or {})" in rendered_operation
    assert "        method='get'," in rendered_operation

    rendered_module = _render_openapi_facade(
        spec_path=Path("solver.json"),
        default_base_url=None,
        operations=(operation,),
    )
    assert "_DEFAULT_BASE_URL = None" in rendered_module
    assert "Cookie" in rendered_module


def test_load_openapi_document_yaml_branch_without_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = tmp_path / "solver.yaml"
    spec.write_text("openapi: 3.1.0\npaths: {}\n", encoding="utf-8")

    original_import_module = importlib.import_module

    def fake_import_module(name: str):  # type: ignore[no-untyped-def]
        if name == "yaml":
            raise ModuleNotFoundError("yaml")
        return original_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(ValueError):
        scaffold_openapi(spec, tmp_path / "out.py")
