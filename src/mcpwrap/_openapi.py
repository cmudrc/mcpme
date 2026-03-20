"""Deterministic facade generation for OpenAPI specifications.

The output is a plain Python module that turns OpenAPI operations into ordinary
Python callables. That generated file can then be discovered by ``mcpwrap`` like
any other source-backed wrapper, keeping the ingestion story inspectable and
deterministic.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._scaffold import ScaffoldedTool, ScaffoldReport, SkippedScaffoldEntry

_HTTP_METHODS = ("delete", "get", "head", "options", "patch", "post", "put")
_METHOD_ORDER = {method: index for index, method in enumerate(_HTTP_METHODS)}
_RESERVED_NAMES = {"base_url", "body", "headers", "timeout_seconds"}


@dataclass(frozen=True, slots=True)
class _OpenApiParameter:
    """Describe one generated OpenAPI operation parameter."""

    name: str
    original_name: str
    location: str
    annotation_source: str
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class _OpenApiOperation:
    """Describe one generated OpenAPI operation wrapper."""

    name: str
    method: str
    path: str
    summary: str
    description: str
    parameters: tuple[_OpenApiParameter, ...]
    body_required: bool
    body_description: str | None
    body_content_type: str | None

    @property
    def source(self) -> str:
        """Return a stable source label for the OpenAPI operation."""
        return f"{self.method.upper()} {self.path}"


def scaffold_openapi(
    spec_path: Path,
    output_path: Path,
    *,
    base_url: str | None = None,
) -> ScaffoldReport:
    """Generate a deterministic facade module for one OpenAPI specification."""
    document = _load_openapi_document(spec_path)
    if "openapi" not in document and "swagger" not in document:
        raise ValueError(f"{spec_path}: file does not look like an OpenAPI document.")

    default_base_url = base_url or _default_base_url(document)
    operations: list[_OpenApiOperation] = []
    skipped: list[SkippedScaffoldEntry] = []

    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError(f"{spec_path}: OpenAPI paths object must be a mapping.")

    for path_name, raw_path_item in sorted(paths.items()):
        if not isinstance(raw_path_item, dict):
            skipped.append(
                SkippedScaffoldEntry(
                    source=str(path_name),
                    reason="path item is not a mapping",
                )
            )
            continue
        path_parameters = _collect_parameters(document, raw_path_item.get("parameters", []))
        for method_name, raw_operation in sorted(
            raw_path_item.items(),
            key=lambda item: _METHOD_ORDER.get(str(item[0]), len(_METHOD_ORDER)),
        ):
            if method_name not in _HTTP_METHODS:
                continue
            if not isinstance(raw_operation, dict):
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{method_name.upper()} {path_name}",
                        reason="operation object is not a mapping",
                    )
                )
                continue
            try:
                operations.append(
                    _operation_from_spec(
                        document=document,
                        path_name=path_name,
                        method_name=method_name,
                        path_parameters=path_parameters,
                        operation=raw_operation,
                    )
                )
            except ValueError as error:
                skipped.append(
                    SkippedScaffoldEntry(
                        source=f"{method_name.upper()} {path_name}",
                        reason=str(error),
                    )
                )

    content = _render_openapi_facade(
        spec_path=spec_path,
        default_base_url=default_base_url,
        operations=tuple(operations),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    generated_tools = tuple(
        ScaffoldedTool(
            name=operation.name,
            kind="openapi_operation",
            style="named",
            source=operation.source,
        )
        for operation in operations
    )
    return ScaffoldReport(
        target_kind="openapi",
        target=str(spec_path),
        output_path=output_path,
        modules_inspected=(),
        generated_tools=generated_tools,
        skipped=tuple(skipped),
    )


def _load_openapi_document(path: Path) -> dict[str, Any]:
    """Load an OpenAPI document from JSON or optional YAML."""
    text = path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        try:
            yaml = importlib.import_module("yaml")
        except ModuleNotFoundError as error:
            raise ValueError(
                f"{path}: YAML OpenAPI specs require PyYAML. Install 'pyyaml' or use JSON."
            ) from error
        loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: OpenAPI document must load into a mapping.")
    return loaded


def _default_base_url(document: dict[str, Any]) -> str | None:
    """Return the first stable server URL declared by the OpenAPI document."""
    servers = document.get("servers", [])
    if not isinstance(servers, list):
        return None
    for server in servers:
        if not isinstance(server, dict):
            continue
        url = server.get("url")
        if isinstance(url, str) and "{" not in url:
            return url
    return None


def _collect_parameters(
    document: dict[str, Any],
    raw_parameters: object,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Collect resolved OpenAPI parameters keyed by location and name."""
    if not isinstance(raw_parameters, list):
        return {}
    collected: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_parameter in raw_parameters:
        parameter = _resolve_mapping_reference(document, raw_parameter)
        if not isinstance(parameter, dict):
            continue
        location = parameter.get("in")
        name = parameter.get("name")
        if not isinstance(location, str) or not isinstance(name, str):
            continue
        collected[(location, name)] = parameter
    return collected


def _operation_from_spec(
    *,
    document: dict[str, Any],
    path_name: str,
    method_name: str,
    path_parameters: dict[tuple[str, str], dict[str, Any]],
    operation: dict[str, Any],
) -> _OpenApiOperation:
    """Build one generated OpenAPI operation specification."""
    merged_parameters = dict(path_parameters)
    merged_parameters.update(_collect_parameters(document, operation.get("parameters", [])))
    used_names: set[str] = set()
    parameters: list[_OpenApiParameter] = []
    for key in sorted(merged_parameters):
        parameter = merged_parameters[key]
        generated = _parameter_from_spec(document, parameter, used_names=used_names)
        if generated is not None:
            parameters.append(generated)

    body_required = False
    body_description: str | None = None
    body_content_type: str | None = None
    request_body = operation.get("requestBody")
    if request_body is not None:
        request_body_mapping = _resolve_mapping_reference(document, request_body)
        if isinstance(request_body_mapping, dict):
            body_required = bool(request_body_mapping.get("required", False))
            description = request_body_mapping.get("description")
            body_description = description if isinstance(description, str) else None
            body_content_type = _preferred_content_type(request_body_mapping)

    operation_id = operation.get("operationId")
    raw_name = (
        operation_id
        if isinstance(operation_id, str)
        else _fallback_operation_name(
            method_name,
            path_name,
        )
    )
    name = _dedupe_name(_sanitize_name(raw_name), used_names)
    summary = operation.get("summary")
    description = operation.get("description")
    title = summary if isinstance(summary, str) else f"{method_name.upper()} {path_name}"
    detail = description if isinstance(description, str) else title
    return _OpenApiOperation(
        name=name,
        method=method_name,
        path=path_name,
        summary=title,
        description=detail,
        parameters=tuple(parameters),
        body_required=body_required,
        body_description=body_description,
        body_content_type=body_content_type,
    )


def _parameter_from_spec(
    document: dict[str, Any],
    parameter: dict[str, Any],
    *,
    used_names: set[str],
) -> _OpenApiParameter | None:
    """Convert one OpenAPI parameter into a generated function parameter."""
    location = parameter.get("in")
    original_name = parameter.get("name")
    if not isinstance(location, str) or not isinstance(original_name, str):
        return None
    schema = _resolve_schema(document, parameter.get("schema"))
    annotation_source = _annotation_from_schema(schema)
    required = bool(parameter.get("required", False)) or location == "path"
    base_name = _sanitize_name(original_name.replace("-", "_"))
    if not base_name:
        raise ValueError(f"unable to build a stable parameter name for {original_name!r}")
    if base_name in _RESERVED_NAMES or base_name in used_names:
        base_name = f"{location}_{base_name}"
    generated_name = _dedupe_name(base_name, used_names)
    description = parameter.get("description")
    if not isinstance(description, str) or not description.strip():
        description = f"{location.title()} parameter {original_name}."
    return _OpenApiParameter(
        name=generated_name,
        original_name=original_name,
        location=location,
        annotation_source=annotation_source,
        required=required,
        description=description,
    )


def _preferred_content_type(request_body: dict[str, Any]) -> str | None:
    """Choose a deterministic request-body content type."""
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return None
    if "application/json" in content:
        return "application/json"
    if "text/plain" in content:
        return "text/plain"
    first = next(iter(sorted(content)), None)
    return first if isinstance(first, str) else None


def _resolve_mapping_reference(document: dict[str, Any], value: object) -> object:
    """Resolve a local ``$ref`` when the referenced value is mapping-like."""
    if not isinstance(value, dict):
        return value
    if "$ref" not in value:
        return value
    reference = value.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError(f"unsupported OpenAPI reference: {reference!r}")
    current: object = document
    for part in reference[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"unable to resolve OpenAPI reference: {reference}")
        current = current[key]
    return current


def _resolve_schema(document: dict[str, Any], raw_schema: object) -> dict[str, Any]:
    """Resolve a schema object into a plain mapping."""
    resolved = _resolve_mapping_reference(document, raw_schema)
    if isinstance(resolved, dict):
        return resolved
    return {}


def _annotation_from_schema(schema: dict[str, Any]) -> str:
    """Map a JSON Schema fragment into a useful Python annotation source."""
    schema_type = schema.get("type")
    if schema_type == "string":
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        return "list[Any]"
    if schema_type == "object":
        return "dict[str, Any]"
    return "Any"


def _fallback_operation_name(method_name: str, path_name: str) -> str:
    """Build a deterministic fallback name for one OpenAPI operation."""
    path_token = path_name.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    path_token = _sanitize_name(path_token) or "root"
    return f"{method_name}_{path_token}"


def _sanitize_name(value: str) -> str:
    """Normalize a string into an MCP-friendly token."""
    sanitized = "".join(character if character.isalnum() else "_" for character in value.lower())
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    return sanitized.strip("_")


def _dedupe_name(base_name: str, used_names: set[str]) -> str:
    """Return a stable unique name while updating the used-name set."""
    candidate = base_name or "operation"
    suffix = 2
    while candidate in used_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _render_openapi_facade(
    *,
    spec_path: Path,
    default_base_url: str | None,
    operations: tuple[_OpenApiOperation, ...],
) -> str:
    """Render the generated Python facade module for an OpenAPI document."""
    parts = [
        f'"""Generated by ``mcpwrap scaffold-openapi`` for ``{spec_path}``.',
        "",
        "This module is deterministic scaffolding around an OpenAPI-described",
        "HTTP surface. It is meant to be inspected and then wrapped through",
        "normal ``mcpwrap`` discovery.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import base64",
        "import json",
        "from typing import Any",
        "from urllib.error import HTTPError, URLError",
        "from urllib.parse import quote, urlencode",
        "from urllib.request import Request, urlopen",
        "",
        f"_DEFAULT_BASE_URL = {default_base_url!r}",
        "",
        "",
        "def _require_base_url(base_url: str | None) -> str:",
        '    """Resolve the effective base URL for one generated operation."""',
        "    resolved = base_url or _DEFAULT_BASE_URL",
        "    if not resolved:",
        "        raise ValueError(",
        "            'No base URL was captured from the OpenAPI document. '",
        "            'Pass base_url explicitly.'",
        "        )",
        "    return resolved.rstrip('/')",
        "",
        "",
        "def _encode_query_value(value: Any) -> str:",
        '    """Convert one query value into a deterministic string."""',
        "    if isinstance(value, bool):",
        "        return 'true' if value else 'false'",
        "    return str(value)",
        "",
        "",
        "def _encode_query(parameters: dict[str, Any]) -> str:",
        '    """Encode non-null query parameters deterministically."""',
        "    filtered: dict[str, list[str] | str] = {}",
        "    for key, value in parameters.items():",
        "        if value is None:",
        "            continue",
        "        if isinstance(value, (list, tuple)):",
        "            filtered[key] = [_encode_query_value(item) for item in value]",
        "            continue",
        "        filtered[key] = _encode_query_value(value)",
        "    return urlencode(filtered, doseq=True)",
        "",
        "",
        "def _encode_body(content_type: str | None, body: Any) -> bytes | None:",
        '    """Encode a request body for transport."""',
        "    if body is None:",
        "        return None",
        "    if content_type == 'text/plain':",
        "        return str(body).encode('utf-8')",
        "    if isinstance(body, bytes):",
        "        return body",
        "    return json.dumps(body, sort_keys=True).encode('utf-8')",
        "",
        "",
        "def _decode_body(raw: bytes, content_type: str | None) -> tuple[Any, str | None]:",
        '    """Decode a response body into JSON, text, or base64."""',
        "    if not raw:",
        "        return None, None",
        "    normalized = (content_type or '').lower()",
        "    if 'json' in normalized:",
        "        return json.loads(raw.decode('utf-8')), None",
        "    try:",
        "        return raw.decode('utf-8'), 'text'",
        "    except UnicodeDecodeError:",
        "        return base64.b64encode(raw).decode('ascii'), 'base64'",
        "",
        "",
        "def _perform_request(",
        "    *,",
        "    method: str,",
        "    url: str,",
        "    headers: dict[str, str],",
        "    body: bytes | None,",
        "    timeout_seconds: float | None,",
        ") -> dict[str, Any]:",
        '    """Execute one HTTP request and normalize the response payload."""',
        "    request = Request(url, data=body, method=method.upper(), headers=headers)",
        "    try:",
        "        with urlopen(request, timeout=timeout_seconds) as response:",
        "            raw = response.read()",
        "            content_type = response.headers.get('Content-Type')",
        "            decoded_body, body_encoding = _decode_body(raw, content_type)",
        "            return {",
        "                'ok': 200 <= response.status < 400,",
        "                'status': response.status,",
        "                'url': url,",
        "                'method': method.upper(),",
        "                'content_type': content_type,",
        "                'body_encoding': body_encoding,",
        "                'headers': dict(response.headers.items()),",
        "                'body': decoded_body,",
        "            }",
        "    except HTTPError as error:",
        "        raw = error.read()",
        "        content_type = error.headers.get('Content-Type')",
        "        decoded_body, body_encoding = _decode_body(raw, content_type)",
        "        return {",
        "            'ok': False,",
        "            'status': error.code,",
        "            'url': url,",
        "            'method': method.upper(),",
        "            'content_type': content_type,",
        "            'body_encoding': body_encoding,",
        "            'headers': dict(error.headers.items()),",
        "            'body': decoded_body,",
        "        }",
        "    except URLError as error:",
        "        return {",
        "            'ok': False,",
        "            'status': None,",
        "            'url': url,",
        "            'method': method.upper(),",
        "            'content_type': None,",
        "            'body_encoding': 'text',",
        "            'headers': {},",
        "            'body': str(error.reason),",
        "        }",
        "",
    ]
    for operation in operations:
        parts.extend(_render_operation(operation))
    return "\n".join(parts).rstrip() + "\n"


def _render_operation(operation: _OpenApiOperation) -> list[str]:
    """Render one generated OpenAPI operation wrapper."""
    signature_lines = _operation_signature_lines(operation)
    docstring_lines = _operation_docstring_lines(operation)
    url_lines = _operation_url_lines(operation)
    body_lines = _operation_body_lines(operation)
    return [
        f"def {operation.name}(",
        *signature_lines,
        ") -> dict[str, Any]:",
        *docstring_lines,
        "    base = _require_base_url(base_url)",
        "    request_headers = dict(headers or {})",
        *url_lines,
        *body_lines,
        "    return _perform_request(",
        f"        method={operation.method!r},",
        "        url=url,",
        "        headers=request_headers,",
        "        body=encoded_body,",
        "        timeout_seconds=timeout_seconds,",
        "    )",
        "",
        "",
    ]


def _operation_signature_lines(operation: _OpenApiOperation) -> list[str]:
    """Render the function signature lines for one OpenAPI operation."""
    lines: list[str] = []
    ordered_parameters = sorted(
        operation.parameters,
        key=lambda parameter: (
            0 if parameter.location == "path" else 1,
            0 if parameter.required else 1,
            parameter.location,
            parameter.name,
        ),
    )
    for parameter in ordered_parameters:
        annotation = parameter.annotation_source
        if parameter.required:
            lines.append(f"    {parameter.name}: {annotation},")
        else:
            lines.append(f"    {parameter.name}: {annotation} | None = None,")
    if operation.body_required:
        lines.append("    body: Any,")
    elif operation.body_content_type is not None:
        lines.append("    body: Any | None = None,")
    lines.extend(
        [
            "    base_url: str | None = None,",
            "    headers: dict[str, str] | None = None,",
            "    timeout_seconds: float | None = None,",
        ]
    )
    return lines


def _operation_docstring_lines(operation: _OpenApiOperation) -> list[str]:
    """Render the docstring block for one OpenAPI operation wrapper."""
    lines = [
        '    """',
        f"    {operation.summary}",
        "",
        f"    Generated wrapper for ``{operation.method.upper()} {operation.path}``.",
    ]
    for parameter in operation.parameters:
        lines.append(f"    :param {parameter.name}: {parameter.description}")
    if operation.body_required or operation.body_content_type is not None:
        description = operation.body_description or "Request body payload."
        lines.append(f"    :param body: {description}")
    lines.extend(
        [
            "    :param base_url: Optional override for the OpenAPI server URL.",
            "    :param headers: Optional additional request headers.",
            "    :param timeout_seconds: Optional request timeout in seconds.",
            "",
            "    :returns: Structured HTTP response details.",
            '    """',
        ]
    )
    return lines


def _operation_url_lines(operation: _OpenApiOperation) -> list[str]:
    """Render URL construction lines for one OpenAPI operation."""
    path_template = operation.path
    for parameter in operation.parameters:
        if parameter.location != "path":
            continue
        path_template = path_template.replace(
            "{" + parameter.original_name + "}",
            "{" + parameter.name + "}",
        )
    lines = [
        f"    path = {path_template!r}.format(",
    ]
    for parameter in operation.parameters:
        if parameter.location == "path":
            lines.append(f"        {parameter.name}=quote(str({parameter.name}), safe=''),")
    lines.append("    )")
    lines.append("    url = base + path")

    query_parameters = [p for p in operation.parameters if p.location == "query"]
    if query_parameters:
        lines.append("    query = _encode_query({")
        for parameter in query_parameters:
            lines.append(f"        {parameter.original_name!r}: {parameter.name},")
        lines.append("    })")
        lines.append("    if query:")
        lines.append("        url = f'{url}?{query}'")

    header_parameters = [p for p in operation.parameters if p.location == "header"]
    for parameter in header_parameters:
        lines.append(f"    if {parameter.name} is not None:")
        lines.append(
            "        request_headers.setdefault("
            f"{parameter.original_name!r}, str({parameter.name}))"
        )

    cookie_parameters = [p for p in operation.parameters if p.location == "cookie"]
    if cookie_parameters:
        lines.append("    cookie_parts: list[str] = []")
        for parameter in cookie_parameters:
            lines.append(f"    if {parameter.name} is not None:")
            lines.append(
                "        cookie_parts.append("
                f"{parameter.original_name!r} + '=' + str({parameter.name}))"
            )
        lines.append("    if cookie_parts:")
        lines.append("        request_headers.setdefault('Cookie', '; '.join(cookie_parts))")
    return lines


def _operation_body_lines(operation: _OpenApiOperation) -> list[str]:
    """Render request-body preparation lines for one OpenAPI operation."""
    lines = ["    encoded_body = None"]
    if operation.body_content_type is None:
        return lines
    lines.append(f"    request_content_type = {operation.body_content_type!r}")
    lines.append("    encoded_body = _encode_body(request_content_type, body)")
    lines.append("    if encoded_body is not None:")
    lines.append("        request_headers.setdefault('Content-Type', request_content_type)")
    return lines
