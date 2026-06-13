"""
LaTeX Parser — .tex → DocumentTree
Handles any ACM sigconf file regardless of section structure.
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from copy import deepcopy


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ContentBlock:
    type: str          # "paragraph" | "figure" | "table" | "verbatim" | "equation" | "raw"
    raw: str           # exact LaTeX
    editable: bool     # False for figures, tables, verbatim envs

@dataclass
class SectionNode:
    id: str                              # slug e.g. "introduction"
    label: str                           # display e.g. "Introduction"
    level: int                           # 1=section 2=subsection 3=subsubsection
    numbered: bool                       # False for abstract, acks
    zone: str                            # "body" | "abstract" | "acks" | "appendix"
    env_wrapper: Optional[str]           # "abstract" | "acks" | None
    label_tag: Optional[str]             # value of \label{} if present
    content_blocks: list = field(default_factory=list)
    children: list = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0

@dataclass
class DocumentTree:
    template_id: str
    preamble: str                        # verbatim, never touch
    metadata_raw: str                    # title/author block verbatim
    title: str                           # extracted for display
    abstract: Optional[SectionNode]
    ccsxml_raw: str                      # verbatim
    keywords: str
    maketitle_line: str                  # "\maketitle" preserved
    body: list                           # list of SectionNode (top-level)
    acks: Optional[SectionNode]
    appendix_sections: list              # list of SectionNode
    bibliography_raw: str                # verbatim


# ── Helpers ────────────────────────────────────────────────────────────────────

PRESERVED_ENVS = {"figure", "figure*", "table", "table*",
                  "verbatim", "lstlisting", "minted",
                  "equation", "equation*", "align", "align*",
                  "algorithmic", "algorithm", "tikzpicture"}

SECTION_RE = re.compile(
    r'^\\(section|subsection|subsubsection)\*?\s*\{([^}]*)\}', re.MULTILINE
)
LABEL_RE  = re.compile(r'\\label\{([^}]+)\}')
TITLE_RE  = re.compile(r'\\title\{([^}]*)\}')
KEYWORDS_RE = re.compile(r'\\keywords\{([^}]*)\}', re.DOTALL)


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_') or 'section'


def unique_id(base: str, seen: set) -> str:
    candidate = base
    i = 2
    while candidate in seen:
        candidate = f"{base}_{i}"
        i += 1
    seen.add(candidate)
    return candidate


def classify_block(raw: str) -> ContentBlock:
    stripped = raw.strip()
    for env in PRESERVED_ENVS:
        if stripped.startswith(f"\\begin{{{env}}}"):
            t = "figure" if "figure" in env else \
                "table"  if "table"  in env else \
                "verbatim" if env in ("verbatim","lstlisting","minted") else \
                "equation" if "equation" in env or "align" in env else "raw"
            return ContentBlock(type=t, raw=raw, editable=False)
    return ContentBlock(type="paragraph", raw=raw, editable=True)


def split_into_blocks(content: str) -> list:
    """Split section content into content blocks, preserving environments."""
    blocks = []
    lines = content.split('\n')
    current_lines = []
    in_env = None
    env_depth = 0

    for line in lines:
        if in_env is None:
            begin_match = re.match(r'\s*\\begin\{(\w+\*?)\}', line)
            if begin_match and begin_match.group(1) in PRESERVED_ENVS:
                # flush current paragraph first
                para = '\n'.join(current_lines).strip()
                if para:
                    blocks.append(classify_block(para))
                current_lines = [line]
                in_env = begin_match.group(1)
                env_depth = 1
            else:
                current_lines.append(line)
        else:
            current_lines.append(line)
            if re.match(rf'\s*\\begin\{{{re.escape(in_env)}\}}', line):
                env_depth += 1
            if re.match(rf'\s*\\end\{{{re.escape(in_env)}\}}', line):
                env_depth -= 1
                if env_depth == 0:
                    blocks.append(classify_block('\n'.join(current_lines)))
                    current_lines = []
                    in_env = None

    # flush remainder
    remainder = '\n'.join(current_lines).strip()
    if remainder:
        blocks.append(classify_block(remainder))

    return blocks


# ── Environment extractor ──────────────────────────────────────────────────────

def extract_env(text: str, env_name: str) -> tuple[str, str, str]:
    """Returns (before, inner_content, after). inner_content is None if not found."""
    begin = f"\\begin{{{env_name}}}"
    end   = f"\\end{{{env_name}}}"
    start = text.find(begin)
    if start == -1:
        return text, None, ""
    inner_start = start + len(begin)
    end_pos = text.find(end, inner_start)
    if end_pos == -1:
        return text, None, ""
    inner = text[inner_start:end_pos]
    after = text[end_pos + len(end):]
    before = text[:start]
    return before, inner, after


# ── Main parser ────────────────────────────────────────────────────────────────

def parse(tex: str, template_id: str = "sigconf") -> DocumentTree:
    seen_ids = set()

    # 1. Split preamble
    doc_start = tex.find("\\begin{document}")
    if doc_start == -1:
        raise ValueError("No \\begin{document} found")
    preamble = tex[:doc_start + len("\\begin{document}")]
    body_raw = tex[doc_start + len("\\begin{document}"):]

    # Strip \end{document} and everything after
    doc_end = body_raw.rfind("\\end{document}")
    if doc_end != -1:
        body_raw = body_raw[:doc_end]

    # 2. Detect template
    detected = template_id
    for tid, hints in {
        "sigconf": ["sigconf"], "acmsmall": ["acmsmall"],
        "acmtog": ["acmtog"], "sigplan": ["sigplan"],
        "manuscript": ["manuscript"]
    }.items():
        if any(h in preamble for h in hints):
            detected = tid
            break

    # 3. Extract special environments from body_raw
    # CCSXML
    before_ccs, ccsxml_inner, after_ccs = extract_env(body_raw, "CCSXML")
    if ccsxml_inner is not None:
        ccsxml_raw = f"\\begin{{CCSXML}}{ccsxml_inner}\\end{{CCSXML}}"
        body_raw = before_ccs + "%%CCSXML_PLACEHOLDER%%\n" + after_ccs
    else:
        ccsxml_raw = ""

    # acks
    before_acks, acks_inner, after_acks = extract_env(body_raw, "acks")
    if acks_inner is not None:
        body_raw = before_acks + "%%ACKS_PLACEHOLDER%%\n" + after_acks
    else:
        acks_inner = None

    # abstract
    before_abs, abstract_inner, after_abs = extract_env(body_raw, "abstract")
    if abstract_inner is not None:
        body_raw = before_abs + "%%ABSTRACT_PLACEHOLDER%%\n" + after_abs
    else:
        abstract_inner = ""

    # 4. Extract metadata block (everything before first placeholder or \section)
    first_section = re.search(r'\\section', body_raw)
    first_placeholder = body_raw.find("%%")
    split_at = min(
        first_section.start() if first_section else len(body_raw),
        first_placeholder if first_placeholder != -1 else len(body_raw)
    )
    metadata_raw = body_raw[:split_at].strip()
    body_raw = body_raw[split_at:]

    # Extract title
    title_m = TITLE_RE.search(preamble + metadata_raw)
    title = title_m.group(1).strip() if title_m else ""

    # Extract keywords
    kw_m = KEYWORDS_RE.search(body_raw)
    keywords = kw_m.group(1).strip() if kw_m else ""
    if kw_m:
        body_raw = body_raw[:kw_m.start()] + "%%KEYWORDS_PLACEHOLDER%%\n" + body_raw[kw_m.end():]

    # maketitle
    maketitle_line = "\\maketitle" if "\\maketitle" in body_raw else ""
    if maketitle_line:
        body_raw = body_raw.replace("\\maketitle", "%%MAKETITLE_PLACEHOLDER%%", 1)

    # 5. Find \appendix divider
    appendix_pos = body_raw.find("\\appendix")
    if appendix_pos != -1:
        appendix_raw = body_raw[appendix_pos + len("\\appendix"):]
        body_raw = body_raw[:appendix_pos]
    else:
        appendix_raw = ""

    # 6. Extract bibliography
    bib_match = re.search(r'\\bibliographystyle.*', body_raw, re.DOTALL)
    if bib_match:
        bibliography_raw = bib_match.group(0).strip()
        body_raw = body_raw[:bib_match.start()]
    else:
        bibliography_raw = ""

    # 7. Parse sections from body_raw
    def parse_sections(text: str, zone: str) -> list:
        """Parse \\section, \subsection, \subsubsection from a text block."""
        # Find all headings with their positions
        headings = []
        for m in re.finditer(
            r'^(\\(?:section|subsection|subsubsection)\*?)\s*\{([^}]*)\}',
            text, re.MULTILINE
        ):
            level_map = {"\\section": 1, "\\section*": 1,
                         "\\subsection": 2, "\\subsection*": 2,
                         "\\subsubsection": 3, "\\subsubsection*": 3}
            level = level_map.get(m.group(1), 1)
            numbered = '*' not in m.group(1)
            headings.append({
                "start": m.start(),
                "end": m.end(),
                "level": level,
                "numbered": numbered,
                "label": m.group(2).strip()
            })

        if not headings:
            return []

        nodes = []
        for i, h in enumerate(headings):
            # Content = from end of heading to start of next heading at same/higher level
            content_start = h["end"]
            content_end = len(text)
            for j in range(i + 1, len(headings)):
                if headings[j]["level"] <= h["level"]:
                    content_end = headings[j]["start"]
                    break

            raw_content = text[content_start:content_end]

            # Check for \label on first line after heading
            label_tag = None
            label_m = LABEL_RE.search(raw_content[:200])
            if label_m:
                label_tag = label_m.group(1)
                raw_content = raw_content[:label_m.start()] + raw_content[label_m.end():]

            node_id = unique_id(slugify(h["label"]), seen_ids)
            node = SectionNode(
                id=node_id,
                label=h["label"],
                level=h["level"],
                numbered=h["numbered"],
                zone=zone,
                env_wrapper=None,
                label_tag=label_tag or f"sec:{node_id}",
                content_blocks=split_into_blocks(raw_content),
                children=[],
                line_start=h["start"],
                line_end=content_end,
            )
            nodes.append(node)

        # Build tree: attach subsections to parent sections
        top_level = []
        stack = []
        for node in nodes:
            while stack and stack[-1].level >= node.level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                top_level.append(node)
            stack.append(node)

        return top_level

    body_sections    = parse_sections(body_raw, "body")
    appendix_sections = parse_sections(appendix_raw, "appendix")

    # 8. Build abstract node
    abstract_node = None
    if abstract_inner is not None:
        abstract_node = SectionNode(
            id="abstract", label="Abstract", level=0,
            numbered=False, zone="abstract",
            env_wrapper="abstract", label_tag=None,
            content_blocks=split_into_blocks(abstract_inner),
        )

    # 9. Build acks node
    acks_node = None
    if acks_inner is not None:
        acks_node = SectionNode(
            id="acks", label="Acknowledgments", level=0,
            numbered=False, zone="acks",
            env_wrapper="acks", label_tag=None,
            content_blocks=split_into_blocks(acks_inner),
        )

    return DocumentTree(
        template_id=detected,
        preamble=preamble,
        metadata_raw=metadata_raw,
        title=title,
        abstract=abstract_node,
        ccsxml_raw=ccsxml_raw,
        keywords=keywords,
        maketitle_line=maketitle_line,
        body=body_sections,
        acks=acks_node,
        appendix_sections=appendix_sections,
        bibliography_raw=bibliography_raw,
    )


# ── Section tree JSON (sent to LLM) ───────────────────────────────────────────

def to_tree_json(tree: DocumentTree) -> dict:
    def node_to_dict(n: SectionNode) -> dict:
        return {
            "id": n.id,
            "label": n.label,
            "level": n.level,
            "zone": n.zone,
            "has_content": any(
                b.raw.strip() for b in n.content_blocks
            ),
            "children": [node_to_dict(c) for c in n.children]
        }

    sections = []
    if tree.abstract:
        sections.append(node_to_dict(tree.abstract))
    for s in tree.body:
        sections.append(node_to_dict(s))
    if tree.acks:
        sections.append(node_to_dict(tree.acks))

    return {
        "title": tree.title,
        "template": tree.template_id,
        "sections": sections,
        "appendix_sections": [node_to_dict(s) for s in tree.appendix_sections]
    }


# ── Find node by ID ────────────────────────────────────────────────────────────

def find_node(tree: DocumentTree, node_id: str) -> Optional[SectionNode]:
    def search(nodes):
        for n in nodes:
            if n.id == node_id:
                return n
            found = search(n.children)
            if found:
                return found
        return None

    candidates = []
    if tree.abstract:
        candidates.append(tree.abstract)
    candidates.extend(tree.body)
    if tree.acks:
        candidates.append(tree.acks)
    candidates.extend(tree.appendix_sections)
    return search(candidates)
