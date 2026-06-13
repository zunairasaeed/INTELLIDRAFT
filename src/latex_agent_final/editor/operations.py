"""
Edit Operations — pure functions on DocumentTree.
Each returns (new_tree, warnings[]).
The LLM never calls these directly — the action dispatcher does.
"""
import re
from copy import deepcopy
from parser.parser import (
    DocumentTree, SectionNode, ContentBlock,
    slugify, unique_id, find_node, split_into_blocks
)

LATEX_ESCAPE = str.maketrans({
    '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
    '_': r'\_', '{': r'\{', '}': r'\}',
    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
})

def escape_latex(text: str) -> str:
    """Escape plain text to safe LaTeX. Preserves existing \\commands."""
    # Don't escape if it looks like the user already wrote LaTeX
    if re.search(r'\\[a-zA-Z]', text):
        return text
    return text.translate(LATEX_ESCAPE)

def text_to_block(text: str) -> ContentBlock:
    return ContentBlock(type="paragraph", raw=escape_latex(text), editable=True)

def collect_all_ids(tree: DocumentTree) -> set:
    ids = set()
    def walk(nodes):
        for n in nodes:
            ids.add(n.id)
            walk(n.children)
    if tree.abstract: ids.add(tree.abstract.id)
    walk(tree.body)
    if tree.acks: ids.add(tree.acks.id)
    walk(tree.appendix_sections)
    return ids


# ── 1. add_paragraph ──────────────────────────────────────────────────────────

def add_paragraph(tree: DocumentTree, target_id: str,
                  content: str, position="end") -> tuple:
    tree = deepcopy(tree)
    node = find_node(tree, target_id)
    if not node:
        return tree, [f"Section '{target_id}' not found"]

    block = text_to_block(content)
    # Only insert among editable blocks
    if position == "start":
        node.content_blocks.insert(0, block)
    elif position == "end":
        node.content_blocks.append(block)
    elif isinstance(position, dict) and "after_index" in position:
        idx = position["after_index"] + 1
        node.content_blocks.insert(idx, block)
    else:
        node.content_blocks.append(block)

    return tree, []


# ── 2. add_section ────────────────────────────────────────────────────────────

def add_section(tree: DocumentTree, after_id: str, label: str) -> tuple:
    tree = deepcopy(tree)
    seen = collect_all_ids(tree)
    node_id = unique_id(slugify(label), seen)
    new_node = SectionNode(
        id=node_id, label=label, level=1, numbered=True,
        zone="body", env_wrapper=None,
        label_tag=f"sec:{node_id}",
    )

    # Find after_id in body list
    for i, s in enumerate(tree.body):
        if s.id == after_id:
            tree.body.insert(i + 1, new_node)
            return tree, []

    # If after_id not found, append
    tree.body.append(new_node)
    return tree, [f"Section '{after_id}' not found — appended at end"]


# ── 3. add_subsection ─────────────────────────────────────────────────────────

def add_subsection(tree: DocumentTree, parent_id: str,
                   label: str, position="end") -> tuple:
    tree = deepcopy(tree)
    seen = collect_all_ids(tree)
    node_id = unique_id(slugify(label), seen)
    new_node = SectionNode(
        id=node_id, label=label, level=2, numbered=True,
        zone="body", env_wrapper=None,
        label_tag=f"sec:{node_id}",
    )

    parent = find_node(tree, parent_id)
    if not parent:
        return tree, [f"Parent section '{parent_id}' not found"]
    if parent.level != 1:
        return tree, [f"Cannot add subsection to a non-section node"]

    if position == "start":
        parent.children.insert(0, new_node)
    else:
        parent.children.append(new_node)
    return tree, []


# ── 4. add_subsubsection ──────────────────────────────────────────────────────

def add_subsubsection(tree: DocumentTree, parent_id: str, label: str) -> tuple:
    tree = deepcopy(tree)
    seen = collect_all_ids(tree)
    node_id = unique_id(slugify(label), seen)
    new_node = SectionNode(
        id=node_id, label=label, level=3, numbered=True,
        zone="body", env_wrapper=None,
        label_tag=f"sec:{node_id}",
    )
    parent = find_node(tree, parent_id)
    if not parent:
        return tree, [f"Parent '{parent_id}' not found"]
    parent.children.append(new_node)
    return tree, []


# ── 5. rename ─────────────────────────────────────────────────────────────────

def rename(tree: DocumentTree, target_id: str, new_label: str) -> tuple:
    tree = deepcopy(tree)
    node = find_node(tree, target_id)
    if not node:
        return tree, [f"Section '{target_id}' not found"]

    old_label_tag = node.label_tag
    node.label = new_label
    new_label_tag = f"sec:{slugify(new_label)}"
    node.label_tag = new_label_tag

    # Update all \ref{} pointing to old label throughout the document
    def update_refs(nodes):
        for n in nodes:
            for b in n.content_blocks:
                if old_label_tag and old_label_tag in b.raw:
                    b.raw = b.raw.replace(
                        f"\\ref{{{old_label_tag}}}",
                        f"\\ref{{{new_label_tag}}}"
                    )
            update_refs(n.children)

    update_refs(tree.body)
    return tree, []


# ── 6. delete ─────────────────────────────────────────────────────────────────

def delete(tree: DocumentTree, target_id: str) -> tuple:
    tree = deepcopy(tree)
    warnings = []

    # Collect all label tags under the target (for broken ref detection)
    target = find_node(tree, target_id)
    if not target:
        return tree, [f"Section '{target_id}' not found"]

    deleted_labels = set()
    def collect_labels(node):
        if node.label_tag:
            deleted_labels.add(node.label_tag)
        for c in node.children:
            collect_labels(c)
    collect_labels(target)

    # Check for broken refs
    def check_refs(nodes):
        for n in nodes:
            for b in n.content_blocks:
                for label in deleted_labels:
                    if f"\\ref{{{label}}}" in b.raw:
                        warnings.append(
                            f"Broken \\ref{{{label}}} in section '{n.label}'"
                        )
            check_refs(n.children)

    check_refs(tree.body)

    # Remove from body
    def remove_from(nodes):
        for i, n in enumerate(nodes):
            if n.id == target_id:
                nodes.pop(i)
                return True
            if remove_from(n.children):
                return True
        return False

    remove_from(tree.body)
    remove_from(tree.appendix_sections)
    return tree, warnings


# ── 7. rewrite ────────────────────────────────────────────────────────────────

def rewrite(tree: DocumentTree, target_id: str, content: str) -> tuple:
    tree = deepcopy(tree)
    node = find_node(tree, target_id)
    if not node:
        return tree, [f"Section '{target_id}' not found"]

    # Keep non-editable blocks (figures, tables, etc.)
    preserved = [b for b in node.content_blocks if not b.editable]
    new_block = text_to_block(content)
    node.content_blocks = [new_block] + preserved
    return tree, []


# ── 8. replace_paragraph ──────────────────────────────────────────────────────

def replace_paragraph(tree: DocumentTree, target_id: str,
                      index: int, content: str) -> tuple:
    tree = deepcopy(tree)
    node = find_node(tree, target_id)
    if not node:
        return tree, [f"Section '{target_id}' not found"]

    editable = [b for b in node.content_blocks if b.editable]
    if index >= len(editable):
        return tree, [f"Paragraph index {index} out of range (section has {len(editable)} paragraphs)"]

    # Find the actual index in content_blocks
    edit_count = 0
    for i, b in enumerate(node.content_blocks):
        if b.editable:
            if edit_count == index:
                node.content_blocks[i] = text_to_block(content)
                break
            edit_count += 1

    return tree, []


# ── 9. move_section ───────────────────────────────────────────────────────────

def move_section(tree: DocumentTree, target_id: str, after_id: str) -> tuple:
    tree = deepcopy(tree)

    # Extract from body
    target = None
    for i, s in enumerate(tree.body):
        if s.id == target_id:
            target = tree.body.pop(i)
            break

    if not target:
        return tree, [f"Section '{target_id}' not found or is a subsection (can't move subsections yet)"]

    # Insert after after_id
    for i, s in enumerate(tree.body):
        if s.id == after_id:
            tree.body.insert(i + 1, target)
            return tree, []

    # after_id not found, append
    tree.body.append(target)
    return tree, [f"Section '{after_id}' not found — moved to end"]


# ── 10. set_title ─────────────────────────────────────────────────────────────

def set_title(tree: DocumentTree, content: str) -> tuple:
    tree = deepcopy(tree)
    tree.title = content
    # Also update in preamble/metadata_raw
    tree.metadata_raw = re.sub(
        r'\\title\{[^}]*\}',
        f'\\title{{{escape_latex(content)}}}',
        tree.metadata_raw
    )
    # Update preamble too if title is there
    tree.preamble = re.sub(
        r'\\title\{[^}]*\}',
        f'\\title{{{escape_latex(content)}}}',
        tree.preamble
    )
    return tree, []


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def execute_action(tree: DocumentTree, action: dict) -> tuple:
    """Route a JSON action to the correct operation."""
    a = action.get("action")

    if a == "add_paragraph":
        return add_paragraph(tree,
            action["target"], action["content"],
            action.get("position", "end"))

    elif a == "add_section":
        return add_section(tree, action["after"], action["label"])

    elif a == "add_subsection":
        return add_subsection(tree,
            action["parent"], action["label"],
            action.get("position", "end"))

    elif a == "add_subsubsection":
        return add_subsubsection(tree, action["parent"], action["label"])

    elif a == "rename":
        return rename(tree, action["target"], action["new_label"])

    elif a == "delete":
        return delete(tree, action["target"])

    elif a == "rewrite":
        return rewrite(tree, action["target"], action["content"])

    elif a == "replace_paragraph":
        return replace_paragraph(tree,
            action["target"], action["index"], action["content"])

    elif a == "move":
        return move_section(tree, action["target"], action["after"])

    elif a == "set_title":
        return set_title(tree, action["content"])

    elif a == "clarify":
        return tree, [f"CLARIFY: {action.get('question', '')}"]

    else:
        return tree, [f"Unknown action: '{a}'"]
