"""
Streamlit test UI for Latex_Alignment (dev only).

Run from repo root:
    streamlit run src/Latex_Alignment/ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
ROOT = UI_DIR.parent
PROJECT_ROOT = ROOT.parent.parent
for path in (str(PROJECT_ROOT), str(ROOT), str(UI_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import streamlit as st
from src.Latex_Alignment.agent.agent import llm_provider_label
from src.Latex_Alignment.session import Session
from helpers import (
    DOC_TITLE_ID,
    count_sections,
    flatten_sections,
    format_action_result,
    refresh_ui_after_structure_change,
    save_section_text,
    section_editor_text,
    section_indent_label,
    section_meta,
)

st.set_page_config(
    page_title="LaTeX Editor — Test UI",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    .block-container { padding-top: 1rem; padding-bottom: 0; max-width: 100%; }
    header[data-testid="stHeader"] { background: transparent; }
    .top-bar {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 10px 16px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    .crumb { color: #64748b; font-size: 13px; }
    .crumb strong { color: #0f172a; }
    .file-pill {
        display: inline-flex; align-items: center; gap: 8px;
        background: #f8fafc; border: 1px solid #e2e8f0;
        border-radius: 8px; padding: 6px 12px; font-size: 13px;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; display: inline-block; }
    .panel {
        background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
        min-height: 72vh; display: flex; flex-direction: column;
    }
    .panel-head {
        padding: 12px 16px; border-bottom: 1px solid #e2e8f0;
        font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: #64748b;
    }
    .section-btn {
        width: 100%; text-align: left; margin-bottom: 4px;
        border: 1px solid transparent !important; border-radius: 8px !important;
    }
    .empty-tag {
        font-size: 10px; background: #fef3c7; color: #92400e;
        padding: 2px 6px; border-radius: 4px; margin-left: 6px;
    }
    .meta-chip {
        display: inline-block; font-size: 11px; color: #64748b;
        background: #f1f5f9; border-radius: 999px; padding: 2px 8px; margin-right: 6px;
    }
    .env-chip {
        display: inline-block; font-size: 11px; color: #1d4ed8;
        background: #dbeafe; border-radius: 999px; padding: 2px 8px;
    }
    .assistant-msg {
        background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 12px 14px; font-size: 14px; line-height: 1.5; margin-bottom: 10px;
    }
    .section-child {
        margin-left: 14px;
        border-left: 2px solid #e2e8f0;
        padding-left: 8px;
    }
    .section-parent-hint {
        font-size: 10px; color: #94a3b8; margin-left: 4px;
    }
    div[data-testid="stTextArea"] textarea {
        font-family: "Consolas", "Courier New", monospace;
        font-size: 14px;
        line-height: 1.55;
    }
</style>
""",
    unsafe_allow_html=True,
)

QUICK_PROMPTS = [
    "Summarize this paper",
    "List all sections",
    "Make this section more formal",
    "Add a paragraph about future work",
]


def init_state() -> None:
    defaults = {
        "doc_session": None,
        "filename": "",
        "selected_section": None,
        "show_ai": True,
        "chat_messages": [],
        "editor_versions": {},
        "structure_version": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_document(tex_bytes: bytes, tex_name: str, bib_bytes: bytes | None, bib_name: str) -> None:
    tex_content = tex_bytes.decode("utf-8", errors="replace")
    bib_content = bib_bytes.decode("utf-8", errors="replace") if bib_bytes else ""
    st.session_state.doc_session = Session(tex_content, bib_content)
    st.session_state.filename = tex_name
    structure = st.session_state.doc_session.get_structure()
    sections = flatten_sections(structure)
    st.session_state.selected_section = sections[0]["id"] if sections else None
    st.session_state.chat_messages = [{
        "role": "assistant",
        "content": (
            f"Indexed **{len(sections)}** sections. Click a section to edit it — "
            "your changes auto-save. Or tell me what to change in plain English."
        ),
    }]
    st.session_state.editor_versions = {}
    st.session_state.structure_version = 0


def _section_subtitle(session, section: dict) -> str:
    meta = section_meta(session, section["id"])
    if section.get("pseudo"):
        return "document title"
    if meta.get("env_tag"):
        return meta["env_tag"]
    lines = meta.get("line_count", 0)
    if lines:
        return f"{lines} line{'s' if lines != 1 else ''}"
    return section.get("zone", "section")


def _render_section_node(session: Session, section: dict, rev: int, depth: int = 0) -> None:
    section_row = dict(section)
    section_row["indent"] = depth
    subtitle = _section_subtitle(session, section_row)
    selected = st.session_state.selected_section == section["id"]
    label = section_indent_label(section_row, subtitle)
    if st.button(
        label,
        key=f"sec_{section['id']}_{rev}",
        use_container_width=True,
        type="primary" if selected else "secondary",
    ):
        st.session_state.selected_section = section["id"]
        st.rerun()

    children = section.get("children") or []
    if children:
        with st.container():
            st.markdown('<div class="section-child">', unsafe_allow_html=True)
            for child in children:
                _render_section_node(session, child, rev, depth + 1)
            st.markdown("</div>", unsafe_allow_html=True)


def _render_contents_tree(session: Session) -> None:
    structure = session.get_structure()
    rev = st.session_state.structure_version

    if structure.get("title"):
        title_section = {
            "id": DOC_TITLE_ID,
            "label": "Title",
            "indent": 0,
            "pseudo": True,
            "children": [],
        }
        _render_section_node(session, title_section, rev)

    for section in structure.get("sections") or []:
        _render_section_node(session, section, rev)

    appendix = structure.get("appendix_sections") or []
    if appendix:
        st.markdown('<span class="section-parent-hint">APPENDIX</span>', unsafe_allow_html=True)
        for section in appendix:
            _render_section_node(session, section, rev)


def render_upload_gate() -> None:
    st.markdown("### Upload a LaTeX file to start")
    st.caption(f"LLM: {llm_provider_label()} — set `GROQ_API_KEY` or `ANTHROPIC_API_KEY` in `.env` for AI edits.")
    col1, col2 = st.columns(2)
    with col1:
        tex_file = st.file_uploader("`.tex` file", type=["tex"], key="upload_tex")
    with col2:
        bib_file = st.file_uploader("`.bib` file (optional)", type=["bib"], key="upload_bib")
    if st.button("Load document", type="primary", disabled=tex_file is None):
        load_document(
            tex_file.getvalue(),
            tex_file.name,
            bib_file.getvalue() if bib_file else None,
            bib_file.name if bib_file else "",
        )
        st.rerun()


def render_top_bar(session: Session) -> None:
    structure = session.get_structure()
    section_count = count_sections(structure)
    c1, c2, c3 = st.columns([4, 3, 3])
    with c1:
        st.markdown(
            f'<div class="crumb">AI Tools › <strong>LaTeX editor</strong></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="file-pill"><span class="dot"></span>{st.session_state.filename} · {section_count} sections</div>',
            unsafe_allow_html=True,
        )
    with c3:
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button("History", use_container_width=True):
                st.session_state.show_history = not st.session_state.get("show_history", False)
        with b2:
            if st.button("Hide AI" if st.session_state.show_ai else "Show AI", use_container_width=True):
                st.session_state.show_ai = not st.session_state.show_ai
        with b3:
            if st.button("Reset", use_container_width=True):
                session.reset()
                refresh_ui_after_structure_change(session)
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": "Document reset to the original upload.",
                })
                st.rerun()
        with b4:
            exported = session.export()
            st.download_button(
                "Export .tex",
                data=exported["tex"],
                file_name=st.session_state.filename or "document.tex",
                mime="text/plain",
                use_container_width=True,
            )


def render_contents(session: Session) -> None:
    st.markdown('<div class="panel-head">CONTENTS</div>', unsafe_allow_html=True)
    _render_contents_tree(session)


def render_editor(session: Session) -> None:
    sid = st.session_state.selected_section
    if not sid:
        st.info("Select a section from the contents panel.")
        return

    meta = section_meta(session, sid)
    chips = [
        f'<span class="meta-chip">Depth {meta.get("depth", 1)}</span>',
    ]
    if meta.get("line_start"):
        chips.append(
            f'<span class="meta-chip">L{meta["line_start"]}–{meta["line_end"]}</span>'
        )
    if meta.get("env_tag"):
        chips.append(f'<span class="env-chip">{meta["env_tag"]}</span>')

    st.markdown(f"## {meta.get('label', sid)}", unsafe_allow_html=False)
    st.markdown("".join(chips), unsafe_allow_html=True)

    text = section_editor_text(session, sid)
    rev = st.session_state.structure_version
    cache_key = f"editor_{sid}_{rev}"
    if cache_key not in st.session_state.editor_versions:
        st.session_state.editor_versions[cache_key] = text

    new_text = st.text_area(
        "Section editor",
        value=st.session_state.editor_versions[cache_key],
        height=420,
        label_visibility="collapsed",
        key=f"textarea_{sid}_{rev}",
    )

    if new_text != st.session_state.editor_versions[cache_key]:
        warnings = save_section_text(session, sid, new_text)
        st.session_state.editor_versions[cache_key] = new_text
        if warnings:
            st.caption(" · ".join(warnings))

    st.caption(
        f"Auto-saves while you type · Ctrl+S · "
        f"{meta.get('line_count', 0)} lines · {meta.get('char_count', 0)} chars"
    )

    with st.form(key=f"section_ai_form_{sid}", clear_on_submit=True):
        ai_line = st.text_input(
            "Ask AI to rewrite this section",
            placeholder="e.g. make this more formal",
        )
        submitted = st.form_submit_button("Ask AI", use_container_width=True)
    if submitted and ai_line.strip():
        run_chat_command(session, ai_line.strip(), context_section=sid)
        st.rerun()


def run_chat_command(session: Session, message: str, context_section: str | None = None) -> None:
    st.session_state.chat_messages.append({"role": "user", "content": message})
    prompt = message
    if context_section:
        meta = section_meta(session, context_section)
        prompt = (
            f'Focus on section "{meta.get("label", context_section)}" (id: {context_section}). '
            f"User request: {message}"
        )
    try:
        result = session.command(prompt)
        reply = format_action_result(result)
        st.session_state.chat_messages.append({"role": "assistant", "content": reply})
        refresh_ui_after_structure_change(session)

        action = result.get("action") or {}
        target = action.get("target") or action.get("parent")
        if target and find_node(session.tree, target):
            st.session_state.selected_section = target
    except Exception as exc:
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": f"Error: {exc}",
        })


def render_assistant(session: Session) -> None:
    st.markdown(
        f'<div class="panel-head">EDIT ASSISTANT · {llm_provider_label()}</div>',
        unsafe_allow_html=True,
    )
    box = st.container(height=520)
    with box:
        for msg in st.session_state.chat_messages:
            if msg["role"] == "assistant":
                with st.chat_message("assistant"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("user"):
                    st.markdown(msg["content"])

    st.markdown("**Try:**")
    chip_cols = st.columns(2)
    for i, prompt in enumerate(QUICK_PROMPTS):
        if chip_cols[i % 2].button(prompt, key=f"chip_{i}", use_container_width=True):
            run_chat_command(session, prompt)
            st.rerun()

    user_input = st.chat_input("Ask anything about your paper…")
    if user_input:
        run_chat_command(session, user_input)
        st.rerun()


def render_history(session: Session) -> None:
    if not st.session_state.get("show_history"):
        return
    with st.expander("Edit history", expanded=True):
        rows = session.get_history()
        if not rows:
            st.caption("No AI edits yet.")
        for row in reversed(rows):
            st.markdown(f"**{row['command']}**")
            st.json(row["action"])
            if row.get("warnings"):
                st.caption("; ".join(row["warnings"]))


def main() -> None:
    init_state()
    session = st.session_state.doc_session

    if session is None:
        render_upload_gate()
        return

    render_top_bar(session)
    render_history(session)

    if st.session_state.show_ai:
        left, center, right = st.columns([1.05, 1.8, 1.1], gap="medium")
    else:
        left, center = st.columns([1.05, 2.9], gap="medium")
        right = None

    with left:
        with st.container(border=True):
            render_contents(session)
    with center:
        with st.container(border=True):
            render_editor(session)
    if right is not None:
        with right:
            with st.container(border=True):
                render_assistant(session)


if __name__ == "__main__":
    main()
