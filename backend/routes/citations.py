import re
import io
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from backend.db import supabase
from backend.routes.auth import get_current_user
from typing import Optional, Union
from fastapi.responses import StreamingResponse, PlainTextResponse
router = APIRouter(prefix="/citations", tags=["Citations"])

# ── models ────────────────────────────────────────────────────────────────

class SaveCitationRequest(BaseModel):
    title:      str
    authors:    list[str]
    year:       Optional[str] = None
    journal:    Optional[str] = None
    doi:        Optional[str] = None
    url:        Optional[str] = None
    abstract:   Optional[str] = None
    session_id: Optional[str] = None

class SemanticPaper(BaseModel):
    title:         str
    authors:       list[Union[dict, str]]
    year:          Optional[Union[int, str]] = None
    venue:         Optional[str] = None
    journal:       Optional[str] = None
    url:           Optional[str] = None
    abstract:      Optional[str] = None
    doi:           Optional[str] = None
    citationCount: Optional[int] = None
    source:        Optional[str] = None


class SaveFromSearchRequest(BaseModel):
    results:    list[SemanticPaper]
    session_id: Optional[str] = None

# ── helpers ───────────────────────────────────────────────────────────────

def make_citation_key(authors: list, year: str, title: str) -> str:
    # extract name if dict, use directly if string
    first = authors[0] if authors else "Unknown"
    if isinstance(first, dict):
        first = first.get("name", "Unknown")
    first_author = first.split()[-1]
    first_author = re.sub(r'[^a-zA-Z]', '', first_author)
    year_str     = str(year) if year else "0000"
    first_word   = re.sub(r'[^a-zA-Z]', '', title.split()[0]) if title else "untitled"
    return f"{first_author}{year_str}{first_word.lower()}"

def format_bibtex_entry(citation: dict) -> str:
    key     = citation.get("citation_key") or "unknown"
    authors = " and ".join(citation.get("authors") or [])
    lines   = [f"@article{{{key},"]
    lines.append(f'  title     = {{{citation.get("title", "")}}},' )
    lines.append(f'  author    = {{{authors}}},')
    if citation.get("journal"):
        lines.append(f'  journal   = {{{citation["journal"]}}},')
    if citation.get("year"):
        lines.append(f'  year      = {{{citation["year"]}}},')
    if citation.get("doi"):
        lines.append(f'  doi       = {{{citation["doi"]}}},')
    if citation.get("url"):
        lines.append(f'  url       = {{{citation["url"]}}},')
    if citation.get("abstract"):
        lines.append(f'  abstract  = {{{citation["abstract"]}}},')
    lines.append("}")
    return "\n".join(lines)

def _save_export_to_storage(user_id: str, content: str, filename: str, filetype: str):
    path     = f"user_files/{user_id}/{uuid.uuid4()}_{filename}"
    contents = content.encode("utf-8")
    supabase.storage.from_("user-files").upload(
        path, contents, {"content-type": "text/plain"}
    )
    supabase.table("user_files").insert({
        "user_id":      user_id,
        "name":         filename,
        "description":  "Auto-exported citations file",
        "file_type":    "latex",
        "storage_path": path,
        "file_size":    len(contents)
    }).execute()

# ── routes ────────────────────────────────────────────────────────────────

@router.post("/save")
def save_citation(body: SaveCitationRequest, user=Depends(get_current_user)):
    existing = supabase.table("citations") \
        .select("id") \
        .eq("user_id", str(user.id)) \
        .eq("title", body.title) \
        .execute()
    if existing.data:
        raise HTTPException(400, "This paper is already in your citations")

    citation_key = make_citation_key(body.authors, body.year, body.title)

    res = supabase.table("citations").insert({
        "user_id":      str(user.id),
        "session_id":   body.session_id,
        "title":        body.title,
        "authors":      body.authors,
        "year":         body.year,
        "journal":      body.journal,
        "doi":          body.doi,
        "url":          body.url,
        "abstract":     body.abstract,
        "citation_key": citation_key
    }).execute()
    return res.data[0]
@router.post("/save-from-search")
def save_from_search(body: SaveFromSearchRequest, user=Depends(get_current_user)):
    saved   = []
    skipped = []

    for paper in body.results:
        # authors are already plain strings — no extraction needed
        author_names = paper.authors

        existing = supabase.table("citations") \
            .select("id") \
            .eq("user_id", str(user.id)) \
            .eq("title", paper.title) \
            .execute()

        if existing.data:
            skipped.append(paper.title)
            continue

        citation_key = make_citation_key(
            author_names,
            paper.year,
            paper.title
        )

        supabase.table("citations").insert({
            "user_id":      str(user.id),
            "session_id":   body.session_id,
            "title":        paper.title,
            "authors":      author_names,
            "year":         paper.year,
            "journal":      paper.journal,
            "doi":          paper.doi,
            "url":          paper.url,
            "abstract":     paper.abstract,
            "citation_key": citation_key
        }).execute()

        saved.append(paper.title)

    return {
        "saved":   saved,
        "skipped": skipped,
        "message": f"{len(saved)} papers saved, {len(skipped)} already existed"
    }
    
@router.get("/")
def list_citations(user=Depends(get_current_user)):
    res = supabase.table("citations") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    return res.data

@router.get("/export/bibtex")
def export_bibtex(
    save_to_storage: bool = False,
    user=Depends(get_current_user)
):
    res = supabase.table("citations") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    if not res.data:
        raise HTTPException(404, "No citations saved yet")

    content = "\n\n".join(format_bibtex_entry(c) for c in res.data)

    if save_to_storage:
        _save_export_to_storage(str(user.id), content, "citations.bib", "latex")

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type = "application/x-bibtex",
        headers    = {"Content-Disposition": "attachment; filename=citations.bib"}
    )

@router.get("/export/latex")
def export_latex(
    save_to_storage: bool = False,
    user=Depends(get_current_user)
):
    res = supabase.table("citations") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    if not res.data:
        raise HTTPException(404, "No citations saved yet")

    lines = [
        r"\documentclass{article}",
        r"\usepackage{hyperref}",
        r"\begin{document}",
        r"\section*{References}",
        r"\begin{enumerate}",
    ]
    for c in res.data:
        authors = ", ".join(c.get("authors") or ["Unknown"])
        year    = c.get("year") or "n.d."
        title   = c.get("title") or ""
        journal = c.get("journal") or ""
        url     = c.get("url") or ""
        doi     = c.get("doi") or ""
        item    = f"  \\item {authors} ({year}). \\textit{{{title}}}. {journal}."
        if doi:
            item += f" DOI: \\href{{https://doi.org/{doi}}}{{{doi}}}."
        elif url:
            item += f" \\url{{{url}}}."
        lines.append(item)

    lines += [r"\end{enumerate}", r"\end{document}"]
    content = "\n".join(lines)

    if save_to_storage:
        _save_export_to_storage(str(user.id), content, "citations.tex", "latex")

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type = "application/x-tex",
        headers    = {"Content-Disposition": "attachment; filename=citations.tex"}
    )
###
@router.get("/export/ieee", response_class=PlainTextResponse)
def export_ieee(user=Depends(get_current_user)):
    res = supabase.table("citations") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    if not res.data:
        raise HTTPException(404, "No citations saved yet")

    lines = []
    for i, c in enumerate(res.data, 1):
        authors  = ", ".join(c.get("authors") or ["Unknown"])
        year     = c.get("year") or "n.d."
        title    = c.get("title") or ""
        journal  = c.get("journal") or ""
        doi      = c.get("doi") or ""
        url      = c.get("url") or ""
        ref      = f'[{i}] {authors}, "{title}," {journal}, {year}.'
        if doi:
            ref += f' doi: {doi}.'
        elif url:
            ref += f' [Online]. Available: {url}.'
        lines.append(ref)

    return "\n\n".join(lines)

@router.get("/export/apa", response_class=PlainTextResponse)
def export_apa(user=Depends(get_current_user)):
    res = supabase.table("citations") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    if not res.data:
        raise HTTPException(404, "No citations saved yet")

    lines = []
    for c in res.data:
        authors  = ", ".join(c.get("authors") or ["Unknown"])
        year     = c.get("year") or "n.d."
        title    = c.get("title") or ""
        journal  = c.get("journal") or ""
        doi      = c.get("doi") or ""
        ref      = f'{authors} ({year}). {title}. {journal}.'
        if doi:
            ref += f' https://doi.org/{doi}'
        lines.append(ref)

    return "\n\n".join(lines)
###


@router.delete("/{citation_id}")
def delete_citation(citation_id: str, user=Depends(get_current_user)):
    res = supabase.table("citations") \
        .select("id") \
        .eq("id", citation_id) \
        .eq("user_id", str(user.id)) \
        .execute()
    if not res.data:
        raise HTTPException(404, "Citation not found")
    supabase.table("citations").delete().eq("id", citation_id).execute()
    return {"message": "Citation deleted"}
