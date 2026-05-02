import logging
import os

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel  # ✅ FIX: added import
from supabase_auth.errors import AuthApiError

from backend.db import supabase
from backend.models import SignupRequest, LoginRequest

router = APIRouter(prefix="/auth", tags=["Auth"])
bearer = HTTPBearer()
log = logging.getLogger(__name__)


@router.post("/signup")
def signup(body: SignupRequest):
    try:
        res = supabase.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {
                "data": {"full_name": body.full_name or ""}
            }
        })
    except AuthApiError as e:
        msg = (e.message or "Signup rejected.").strip()
        code = e.code
        log.warning(
            "Supabase rejected signup for %s — error_code=%r message=%s",
            body.email,
            code,
            msg,
        )
        if code == "user_already_exists" or "already registered" in msg.lower():
            detail = (
                f"{msg} Use Forgot password / reset in Dashboard → Authentication → Users "
                "or sign in instead."
            )
        else:
            detail = msg
        raise HTTPException(status_code=400, detail=detail)

    if res.user is None:
        raise HTTPException(status_code=400, detail="Signup failed — check your email/password")
    return {"message": "Signup successful — check your email to confirm"}


@router.post("/login")
def login(body: LoginRequest):
    try:
        res = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })
    except AuthApiError as e:
        msg = (e.message or "Could not sign in.").strip()
        code = e.code
        log.warning(
            "Supabase rejected login for %s — error_code=%r message=%s",
            body.email,
            code,
            msg,
        )
        # "Invalid login credentials" maps to invalid_credentials — often wrong password
        # or signing in against a different project than signup. Confirm hint only when precise.
        if code == "email_not_confirmed":
            detail = (
                f"{msg} Open Supabase → Authentication → Users and confirm this user, "
                "or sign up again after disabling “Confirm email”."
            )
        elif code == "invalid_credentials" or "invalid login" in msg.lower():
            detail = (
                f"{msg} Most often: wrong password, or SUPABASE_URL / SUPABASE_KEY in your "
                ".env points to a different Supabase project than the Dashboard you're checking. "
                "Try Forgot password, or reset the password for this user under Users → … menu."
            )
        else:
            detail = msg
        raise HTTPException(status_code=401, detail=detail)

    if res.user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if res.session is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Account found but no session was issued. "
                "Confirm your email (Supabase → Authentication → Users), or turn off "
                "\"Confirm email\" for local testing."
            ),
        )

    # archive sessions older than 30 days on every login
    try:
        supabase.rpc("archive_old_sessions").execute()
    except Exception:
        pass  # login still succeeds if RPC missing or fails

    return {
        "access_token": res.session.access_token,
        "user_id": str(res.user.id),
        "email": res.user.email,
        "full_name": res.user.user_metadata.get("full_name", "")
    }


@router.post("/logout")
def logout(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    supabase.auth.sign_out()
    return {"message": "Logged out"}


# ── reusable dependency ────────────────────────────────────────────────────
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    token = creds.credentials
    res = supabase.auth.get_user(token)
    if res.user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token — please log in again")
    return res.user


# ✅ FIX: BaseModel now works
class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest):
    redirect_to = (os.getenv("PASSWORD_RESET_REDIRECT_URL") or "").strip()
    try:
        if redirect_to:
            supabase.auth.reset_password_email(
                body.email,
                options={"redirect_to": redirect_to},
            )
        else:
            supabase.auth.reset_password_email(body.email)
    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=e.message or "Could not send reset email.")
    return {"message": "Password reset email sent"}