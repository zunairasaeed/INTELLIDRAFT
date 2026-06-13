"""
Serializer — DocumentTree → valid .tex string.
Deterministic. Preamble, bibliography, CCSXML are verbatim.
"""
from ..parser.parser import DocumentTree, SectionNode, ContentBlock


def serialize_blocks(blocks: list) -> str:
    parts = []
    for b in blocks:
        raw = b.raw.strip()
        if raw:
            parts.append(raw)
    return "\n\n".join(parts)


def serialize_node(node: SectionNode, is_appendix: bool = False) -> str:
    parts = []

    level_cmd = {1: "\\section", 2: "\\subsection", 3: "\\subsubsection"}
    cmd = level_cmd.get(node.level, "\\section")
    if not node.numbered:
        cmd += "*"

    # Heading line
    parts.append(f"{cmd}{{{node.label}}}")

    # Label tag (only for numbered sections)
    if node.label_tag and node.numbered:
        parts.append(f"\\label{{{node.label_tag}}}")

    # Content blocks
    body = serialize_blocks(node.content_blocks)
    if body:
        parts.append(body)

    # Children (subsections)
    for child in node.children:
        parts.append("")  # blank line before subsection
        parts.append(serialize_node(child, is_appendix))

    return "\n".join(parts)


def serialize(tree: DocumentTree) -> str:
    out = []

    # 1. Preamble (verbatim)
    out.append(tree.preamble)
    out.append("")

    # 2. Metadata (verbatim)
    if tree.metadata_raw.strip():
        out.append(tree.metadata_raw.strip())
        out.append("")

    # 3. Abstract
    if tree.abstract:
        out.append("\\begin{abstract}")
        out.append(serialize_blocks(tree.abstract.content_blocks))
        out.append("\\end{abstract}")
        out.append("")

    # 4. CCSXML (verbatim)
    if tree.ccsxml_raw.strip():
        out.append(tree.ccsxml_raw.strip())
        out.append("")

    # 5. Keywords
    if tree.keywords.strip():
        out.append(f"\\keywords{{{tree.keywords.strip()}}}")
        out.append("")

    # 6. \maketitle
    if tree.maketitle_line:
        out.append(tree.maketitle_line)
        out.append("")

    # 7. Body sections
    for section in tree.body:
        out.append("")  # blank line before each section
        out.append(serialize_node(section))
        out.append("")

    # 8. Acks
    if tree.acks:
        out.append("\\begin{acks}")
        out.append(serialize_blocks(tree.acks.content_blocks))
        out.append("\\end{acks}")
        out.append("")

    # 9. Bibliography (verbatim)
    if tree.bibliography_raw.strip():
        out.append(tree.bibliography_raw.strip())
        out.append("")

    # 10. Appendix
    if tree.appendix_sections:
        out.append("\\appendix")
        out.append("")
        for section in tree.appendix_sections:
            out.append(serialize_node(section, is_appendix=True))
            out.append("")

    # 11. Close
    out.append("\\end{document}")

    return "\n".join(out)
