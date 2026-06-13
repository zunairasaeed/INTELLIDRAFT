"""
Session — ties parser + agent + operations + serializer together.
One session per uploaded document.
"""
from copy import deepcopy
from parser.parser import parse, DocumentTree, to_tree_json
from editor.operations import execute_action
from editor.serializer import serialize
from agent.agent import get_action
import re


def extract_bib_keys(bib_content: str) -> list:
    """Extract all citation keys from a .bib file."""
    return re.findall(r'@\w+\{([^,]+),', bib_content)


class Session:
    def __init__(self, tex_content: str, bib_content: str = "",
                 template_id: str = "sigconf"):
        self.original_tex  = tex_content
        self.bib_content   = bib_content
        self.bib_keys      = extract_bib_keys(bib_content) if bib_content else []
        self.tree          = parse(tex_content, template_id)
        self.snapshots     = []          # list of DocumentTree (for undo)
        self.history       = []          # list of {command, action, warnings}

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_structure(self) -> dict:
        """Return section tree JSON for frontend sidebar."""
        return to_tree_json(self.tree)

    def command(self, user_message: str) -> dict:
        """
        Process a natural-language command.
        Returns {action, warnings, structure} — never the full .tex.
        """
        # 1. LLM → action JSON
        action = get_action(self.tree, user_message, self.bib_keys)

        if action.get("action") == "clarify":
            return {
                "action": action,
                "warnings": [],
                "clarification": action.get("question"),
                "structure": to_tree_json(self.tree)
            }

        # 2. Save snapshot for undo
        self.snapshots.append(deepcopy(self.tree))

        # 3. Execute
        new_tree, warnings = execute_action(self.tree, action)
        self.tree = new_tree

        # 4. Log
        self.history.append({
            "command": user_message,
            "action": action,
            "warnings": warnings
        })

        return {
            "action": action,
            "warnings": warnings,
            "structure": to_tree_json(self.tree)
        }

    def export(self) -> dict:
        """Serialize current tree back to .tex. .bib is unchanged."""
        return {
            "tex": serialize(self.tree),
            "bib": self.bib_content
        }

    def undo(self) -> dict:
        """Roll back the last command."""
        if self.snapshots:
            self.tree = self.snapshots.pop()
            if self.history:
                self.history.pop()
        return {"structure": to_tree_json(self.tree)}

    def reset(self) -> dict:
        """Restore to original uploaded file."""
        self.tree = parse(self.original_tex)
        self.snapshots = []
        self.history = []
        return {"structure": to_tree_json(self.tree)}

    def get_history(self) -> list:
        return self.history
