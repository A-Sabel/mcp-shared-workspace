"""Small fixes for JSON Schema details omitted by the MCP SDK generator."""

from mcp.server.mcpserver import MCPServer


def set_explicit_required(
    mcp: MCPServer,
    tool_name: str,
    *,
    one_of: list[dict[str, object]] | None = None,
) -> None:
    """Ensure a tool schema has a root required list, including when empty."""
    tool = mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"Cannot find registered MCP tool {tool_name!r}.")
    tool.parameters["required"] = []
    if one_of is not None:
        tool.parameters["oneOf"] = one_of


def set_property_type(mcp: MCPServer, tool_name: str, property_name: str, json_type: str) -> None:
    """Expose a simple non-null JSON type for an optional argument."""
    tool = mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"Cannot find registered MCP tool {tool_name!r}.")
    prop = tool.parameters.get("properties", {}).get(property_name)
    if prop is None:
        raise RuntimeError(f"Tool {tool_name!r} has no property {property_name!r}.")
    alternatives = prop.pop("anyOf", [])
    typed_alternative = next(
        (entry for entry in alternatives if entry.get("type") == json_type), {}
    )
    for key, value in typed_alternative.items():
        if key != "type":
            prop.setdefault(key, value)
    prop.pop("default", None)
    prop["type"] = json_type


def set_array_item_schema(
    mcp: MCPServer,
    tool_name: str,
    property_name: str,
    item_schema: dict[str, object],
) -> None:
    """Inline an array's item schema for clients that don't resolve $refs."""
    tool = mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"Cannot find registered MCP tool {tool_name!r}.")
    prop = tool.parameters.get("properties", {}).get(property_name)
    if prop is None:
        raise RuntimeError(f"Tool {tool_name!r} has no property {property_name!r}.")
    alternatives = prop.pop("anyOf", [])
    array_alternative = next(
        (entry for entry in alternatives if entry.get("type") == "array"), {}
    )
    for key, value in array_alternative.items():
        if key not in {"type", "items"}:
            prop.setdefault(key, value)
    prop.pop("default", None)
    prop["type"] = "array"
    prop["items"] = item_schema
    tool.parameters.pop("$defs", None)
