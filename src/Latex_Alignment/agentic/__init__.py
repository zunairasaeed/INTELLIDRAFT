"""Agentic subpackage: natural-language intent routing + execution."""

from .executor import ExecutionResult, execute
from .intent_router import RoutedIntent, route_intent

__all__ = [
    "RoutedIntent",
    "route_intent",
    "ExecutionResult",
    "execute",
]
