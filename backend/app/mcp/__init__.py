"""MCP adapter: exposes Project Moah to coding agents over a local stdio connection.

Kept apart from the domain code so vendor setup changes never touch services. Everything
here calls the same services as the desktop app; none of the rules are duplicated.
"""
