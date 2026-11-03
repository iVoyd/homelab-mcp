class ToolError(Exception):
    """The call was allowed but failed (command error, bad output, timeout)."""


class ToolDenied(ToolError):
    """The call was refused by policy (namespace, alias, path, SQL guard...)."""
