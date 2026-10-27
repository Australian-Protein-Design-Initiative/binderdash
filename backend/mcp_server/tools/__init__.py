"""Tool registration. Each module owns one slice of the surface."""

from __future__ import annotations

from typing import Any


def register_tools(mcp: Any) -> None:
    from . import designs, discovery, prepare, selection, structures, target_contacts

    discovery.register(mcp)
    designs.register(mcp)
    selection.register(mcp)
    structures.register(mcp)
    prepare.register(mcp)
    target_contacts.register(mcp)
