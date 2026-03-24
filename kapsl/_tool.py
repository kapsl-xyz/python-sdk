"""Tool decorator, JSON Schema generation, and tool code generation."""

import ast
import inspect
import re
import textwrap
import typing
from pathlib import Path


def tool(fn):
    """Mark a function as a Kapsl tool.

    Attaches metadata used by Agent and Client to build tool definitions
    and generate the bundled tool_code script.
    """
    hints = typing.get_type_hints(fn)
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""

    fn._kapsl_tool = True
    fn._kapsl_name = fn.__name__
    fn._kapsl_description = doc.split("\n\n")[0].strip()  # first paragraph
    fn._kapsl_input_schema = _schema_from_hints(sig, hints, doc)
    return fn


# --- Schema generation ---

_TYPE_MAP = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
}


def _resolve_type(tp):
    """Convert a Python type annotation to a JSON Schema fragment."""
    if tp in _TYPE_MAP:
        return dict(_TYPE_MAP[tp])

    # Bare list/dict without type args
    if tp is list:
        return {"type": "array"}
    if tp is dict:
        return {"type": "object"}

    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    # list[X]
    if origin is list:
        item_type = args[0] if args else str
        return {"type": "array", "items": _resolve_type(item_type)}

    # dict[str, X]
    if origin is dict:
        val_type = args[1] if len(args) > 1 else str
        return {"type": "object", "additionalProperties": _resolve_type(val_type)}

    import warnings
    warnings.warn(f"Unsupported type annotation {tp!r}, defaulting to string schema", stacklevel=3)
    return {"type": "string"}


def _is_union(tp):
    """Check if a type is a Union (typing.Union or PEP 604 X | Y)."""
    import types as _types
    return typing.get_origin(tp) is typing.Union or isinstance(tp, _types.UnionType)


def _is_optional(tp):
    """Check if a type is Optional[X] or X | None."""
    if not _is_union(tp):
        return False
    return type(None) in typing.get_args(tp)


def _unwrap_optional(tp):
    """Extract T from Optional[T]."""
    args = typing.get_args(tp)
    non_none = [a for a in args if a is not type(None)]
    return non_none[0] if non_none else str


def _parse_arg_descriptions(doc: str) -> dict[str, str]:
    """Extract parameter descriptions from Google-style docstring Args section."""
    descriptions = {}
    in_args = False
    current_param = None
    current_desc = []

    for line in doc.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            # New section header (e.g., Returns:, Raises:)
            if stripped and not stripped.startswith(" ") and stripped.endswith(":") and not stripped.startswith("-"):
                # Check if it's indented relative to Args — if not, it's a new section
                if not line.startswith(" " * 4) and not line.startswith("\t\t"):
                    break
            # Parameter line: "  param_name: description" or "  param_name (type): description"
            m = re.match(r"\s{2,}(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)", line)
            if m:
                if current_param:
                    descriptions[current_param] = " ".join(current_desc).strip()
                current_param = m.group(1)
                current_desc = [m.group(2)] if m.group(2) else []
            elif current_param and stripped:
                # Continuation line
                current_desc.append(stripped)
            elif not stripped:
                if current_param:
                    descriptions[current_param] = " ".join(current_desc).strip()
                    current_param = None
                    current_desc = []

    if current_param:
        descriptions[current_param] = " ".join(current_desc).strip()

    return descriptions


def _schema_from_hints(sig: inspect.Signature, hints: dict, doc: str) -> dict:
    """Build a JSON Schema object from function signature and type hints."""
    properties = {}
    required = []
    arg_descs = _parse_arg_descriptions(doc)

    for name, param in sig.parameters.items():
        tp = hints.get(name)
        if tp is None:
            tp = str  # no annotation → string

        # Skip return type
        if name == "return":
            continue

        optional = _is_optional(tp)
        if optional:
            tp = _unwrap_optional(tp)

        prop = _resolve_type(tp)
        if name in arg_descs:
            prop["description"] = arg_descs[name]

        properties[name] = prop

        # Required if: no default AND not Optional
        if param.default is inspect.Parameter.empty and not optional:
            required.append(name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# --- Tool definitions (for API) ---

def _build_tool_defs(tools: list) -> list[dict]:
    """Build the tool definitions list for the Anthropic API."""
    defs = []
    for fn in tools:
        defs.append({
            "name": fn._kapsl_name,
            "description": fn._kapsl_description,
            "input_schema": fn._kapsl_input_schema,
        })
    return defs


# --- Code generation ---

def _extract_imports(fn) -> list[str]:
    """Extract import statements from the module where fn is defined."""
    try:
        source_file = inspect.getfile(fn)
    except (TypeError, OSError):
        return []

    try:
        source = Path(source_file).read_text()
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            line = ast.get_source_segment(source, node)
            if line:
                imports.append(line)
        elif isinstance(node, ast.ImportFrom):
            # Skip kapsl imports
            if node.module and node.module.startswith("kapsl"):
                continue
            line = ast.get_source_segment(source, node)
            if line:
                imports.append(line)

    return imports


def _extract_function_source(fn) -> str:
    """Get the source of fn, stripping the @tool decorator line."""
    source = inspect.getsource(fn)
    source = textwrap.dedent(source)
    lines = source.split("\n")
    # Strip @tool decorator line(s)
    filtered = []
    skip_next = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("@tool"):
            continue
        filtered.append(line)
    return "\n".join(filtered)


_DISPATCH_LOOP = '''
_TOOLS = {%s}

import sys as _sys, json as _json
for _line in _sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    _req = _json.loads(_line)
    _fn = _TOOLS.get(_req["name"])
    if _fn is None:
        print(_json.dumps({"error": f"tool \\'{_req['name']}\\' not found"}))
    else:
        try:
            _result = _fn(**_req["input"])
            _out = _result if isinstance(_result, (dict, list, str, int, float, bool, type(None))) else str(_result)
            print(_json.dumps({"output": _out}))
        except Exception as _e:
            print(_json.dumps({"error": str(_e)}))
    _sys.stdout.flush()
'''


def generate_tool_code(tools: list) -> str:
    """Generate a complete, self-contained Python script for tool execution."""
    # Collect imports from all tool modules (deduplicated)
    seen_imports = set()
    import_lines = []
    for fn in tools:
        for imp in _extract_imports(fn):
            if imp not in seen_imports:
                seen_imports.add(imp)
                import_lines.append(imp)

    # Collect function sources
    func_sources = []
    for fn in tools:
        func_sources.append(_extract_function_source(fn))

    # Build tool map string
    tool_map = ", ".join(f'"{fn._kapsl_name}": {fn._kapsl_name}' for fn in tools)

    parts = []
    if import_lines:
        parts.append("\n".join(import_lines))
        parts.append("")
    parts.append("\n\n".join(func_sources))
    parts.append(_DISPATCH_LOOP % tool_map)

    return "\n".join(parts)
