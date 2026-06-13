"""Session — ties parser + agent + operations + serializer together."""

from __future__ import annotations

import re
from copy import deepcopy

from .agent.agent import get_action
from .editor.operations import execute_action
from .editor.serializer import serialize
from .parser.parser import parse, to_tree_json


READ_ONLY_ACTIONS = frozenset({"list_sections", "show_section", "summarize", "get_structure", "clarify"})


def _collect_section_ids(structure: dict) -> list[str]:
    ids: list[str] = []

    def walk(nodes: list) -> None:
        for node in nodes:
            ids.append(node["id"])
            walk(node.get("children", []))

    walk(structure.get("sections", []))
    walk(structure.get("appendix_sections", []))
    return ids


def extract_bib_keys(bib_content: str) -> list[str]:
    return re.findall(r"@\w+\{([^,]+),", bib_content)


class Session:
    def __init__(self, tex_content: str, bib_content: str = "", template_id: str = "sigconf") -> None:
        self.original_tex = tex_content
        self.bib_content = bib_content
        self.bib_keys = extract_bib_keys(bib_content) if bib_content else []
        self.tree = parse(tex_content, template_id)
        self.snapshots: list = []
        self.history: list = []

    def get_structure(self) -> dict:
        return to_tree_json(self.tree)

    def command(self, user_message: str) -> dict:
        action = get_action(self.tree, user_message, self.bib_keys)
        act = action.get("action")

        if act == "clarify":
            return {
                "action": action,
                "warnings": [],
                "clarification": action.get("question"),
                "structure": to_tree_json(self.tree),
            }

        if act in READ_ONLY_ACTIONS:
            if act == "list_sections" and "sections" not in action:
                action["sections"] = _collect_section_ids(to_tree_json(self.tree))
            return {
                "action": action,
                "warnings": [],
                "structure": to_tree_json(self.tree),
            }

        self.snapshots.append(deepcopy(self.tree))
        new_tree, warnings = execute_action(self.tree, action)
        self.tree = new_tree
        self.history.append({"command": user_message, "action": action, "warnings": warnings})

        return {
            "action": action,
            "warnings": warnings,
            "structure": to_tree_json(self.tree),
        }

    def export(self) -> dict:
        return {"tex": serialize(self.tree), "bib": self.bib_content}

    def undo(self) -> dict:
        if self.snapshots:
            self.tree = self.snapshots.pop()
            if self.history:
                self.history.pop()
        return {"structure": to_tree_json(self.tree)}

    def reset(self) -> dict:
        self.tree = parse(self.original_tex)
        self.snapshots = []
        self.history = []
        return {"structure": to_tree_json(self.tree)}

    def get_history(self) -> list:
        return self.history
