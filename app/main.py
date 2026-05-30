from __future__ import annotations

from pathlib import Path
from typing import Any
import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from .auth import auth_dependency, create_access_token, hash_password, verify_password
from .database import Database
from .excel_service import (
    apply_parsed_inquiry,
    create_brand_task,
    export_task,
    fill_row_from_talent,
    import_ratecard,
    resolve_inquiry_row_index,
    save_upload,
)
from .llm_service import parse_inquiry_text


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
REGISTER_INVITE_CODE = os.getenv("REGISTER_INVITE_CODE", "").strip()
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]

app = FastAPI(title="小红书媒介自动填表网站", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = Database()
current_user = auth_dependency(db)


class AuthRequest(BaseModel):
    username: str
    password: str
    invite_code: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: dict[str, Any]


class SaveRowsRequest(BaseModel):
    rows: list[dict[str, Any]]
    missing: dict[str, Any] = {}


class FillTalentRequest(BaseModel):
    row_index: int
    query: str | None = None
    talent_id: int | None = None


class InquiryRequest(BaseModel):
    row_index: int
    text: str
    match_query: str | None = None
    confirmed_row_index: int | None = None


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["id"], "username": user["username"], "created_at": user.get("created_at")}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=AuthResponse)
def register(body: AuthRequest) -> dict[str, Any]:
    username = body.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 个字符")
    if REGISTER_INVITE_CODE and body.invite_code != REGISTER_INVITE_CODE:
        raise HTTPException(status_code=403, detail="邀请码不正确")
    if db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    try:
        user = db.create_user(username, hash_password(body.password))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    return {"token": create_access_token(user["id"]), "user": public_user(user)}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: AuthRequest) -> dict[str, Any]:
    user = db.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    return {"token": create_access_token(user["id"]), "user": public_user(user)}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": public_user(user)}


@app.post("/api/ratecards")
async def upload_ratecard(file: UploadFile = File(...), user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    path = await save_upload(file, "ratecards", owner_id=user["id"])
    result = import_ratecard(path)
    version_id = db.create_ratecard_version(
        user_id=user["id"],
        filename=file.filename or path.name,
        stored_path=str(path),
        sheet_name=result["sheet_name"],
        header_row=result["header_row"],
        talents=result["talents"],
    )
    return {"version_id": version_id, "talent_count": len(result["talents"]), "sheet_name": result["sheet_name"]}


@app.get("/api/ratecards/latest")
def latest_ratecard(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"ratecard": db.latest_ratecard_version(user["id"])}


@app.get("/api/talents/search")
def search_talents(q: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not q.strip():
        return {"items": []}
    return {"items": db.search_talents(user["id"], q)}


@app.post("/api/tasks")
async def create_task(
    file: UploadFile = File(...), brand_name: str | None = Form(None), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    path = await save_upload(file, "brand_tasks", owner_id=user["id"])
    task = create_brand_task(path, brand_name)
    task_id = db.create_task(user["id"], task)
    return {"task_id": task_id, "task": db.get_task(user["id"], task_id)}


@app.get("/api/tasks")
def list_tasks(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"items": db.list_tasks(user["id"])}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    task = db.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}


@app.put("/api/tasks/{task_id}/rows")
def save_rows(task_id: int, body: SaveRowsRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, str]:
    task = db.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.save_task_rows(user["id"], task_id, body.rows, body.missing)
    return {"status": "saved"}


@app.post("/api/tasks/{task_id}/fill-from-talent")
def fill_from_talent(task_id: int, body: FillTalentRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    task = db.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    talent = db.get_talent(user["id"], body.talent_id) if body.talent_id else None
    if not talent and body.query:
        candidates = db.search_talents(user["id"], body.query, limit=1)
        talent = candidates[0] if candidates else None
    if not talent:
        raise HTTPException(status_code=404, detail="没有匹配到达人")
    updated = fill_row_from_talent(task, body.row_index, talent)
    db.save_task_rows(user["id"], task_id, updated["rows"], updated["missing"])
    return {"task": db.get_task(user["id"], task_id), "talent": talent}


@app.post("/api/tasks/{task_id}/parse-inquiry")
def parse_inquiry(task_id: int, body: InquiryRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    task = db.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    headers = [column["header"] for column in task["columns"]]
    parsed = parse_inquiry_text(body.text, headers)
    target_row_index, match_info = resolve_inquiry_row_index(
        task,
        parsed,
        body.match_query,
        body.confirmed_row_index,
        body.row_index,
    )
    if target_row_index is None:
        return {"task": task, "parsed": parsed, "target_row_index": None, "match_info": match_info, "applied": False}
    updated = apply_parsed_inquiry(task, target_row_index, parsed)
    db.save_task_rows(user["id"], task_id, updated["rows"], updated["missing"])
    return {
        "task": db.get_task(user["id"], task_id),
        "parsed": parsed,
        "target_row_index": target_row_index,
        "match_info": match_info,
        "applied": True,
    }


@app.get("/api/tasks/{task_id}/export")
def export(task_id: int, user: dict[str, Any] = Depends(current_user)) -> FileResponse:
    task = db.get_task(user["id"], task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    path = export_task(task)
    return FileResponse(
        path,
        filename=f"品牌表格_已填写_{task_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

