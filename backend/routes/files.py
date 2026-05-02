from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from backend.db import supabase
from backend.routes.auth import get_current_user
import uuid

router = APIRouter(prefix="/files", tags=["Files"])

# ── shared files (read by everyone) ───────────────────────────────────────

@router.get("/shared")
def list_shared_files(folder_id: str = None, user=Depends(get_current_user)):
    query = supabase.table("shared_files").select("*")
    if folder_id:
        query = query.eq("folder_id", folder_id)
    return query.execute().data

@router.get("/folders")
def list_folders(user=Depends(get_current_user)):
    return supabase.table("folder_tree").select("*").execute().data

# ── private user files ─────────────────────────────────────────────────────

@router.get("/my")
def list_my_files(user=Depends(get_current_user)):
    res = supabase.table("user_files") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .order("created_at", desc=True) \
        .execute()
    return res.data

@router.post("/my/upload")
async def upload_my_file(
    file: UploadFile = File(...),
    description: str = Form(""),
    user=Depends(get_current_user)
):
    contents  = await file.read()
    ext       = file.filename.split(".")[-1].lower()
    file_type = ext if ext in ["pdf", "docx", "latex"] else "other"
    path      = f"user_files/{user.id}/{uuid.uuid4()}_{file.filename}"

    # upload to supabase storage bucket "user-files"
    supabase.storage.from_("user-files").upload(path, contents)

    # save metadata to user_files table
    res = supabase.table("user_files").insert({
        "user_id":      str(user.id),
        "name":         file.filename,
        "description":  description,
        "file_type":    file_type,
        "storage_path": path,
        "file_size":    len(contents)
    }).execute()

    return res.data[0]

@router.get("/my/{file_id}/download")
def get_download_url(file_id: str, user=Depends(get_current_user)):
    # verify file belongs to this user
    res = supabase.table("user_files") \
        .select("*") \
        .eq("id", file_id) \
        .eq("user_id", str(user.id)) \
        .single() \
        .execute()
    if not res.data:
        raise HTTPException(404, "File not found")

    url = supabase.storage.from_("user-files") \
        .create_signed_url(res.data["storage_path"], 3600)
    return {"download_url": url["signedURL"]}

@router.delete("/my/{file_id}")
def delete_my_file(file_id: str, user=Depends(get_current_user)):
    res = supabase.table("user_files") \
        .select("storage_path") \
        .eq("id", file_id) \
        .eq("user_id", str(user.id)) \
        .single() \
        .execute()
    if not res.data:
        raise HTTPException(404, "File not found")

    supabase.storage.from_("user-files").remove([res.data["storage_path"]])
    supabase.table("user_files").delete().eq("id", file_id).execute()
    return {"message": "File deleted"}