from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    case,
    create_engine,
    desc,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, RowMapping


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DATABASE_PATH.as_posix()}"


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(255), nullable=False, unique=True, index=True),
    Column("password_hash", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

ratecard_versions = Table(
    "ratecard_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=True, index=True),
    Column("filename", Text, nullable=False),
    Column("stored_path", Text, nullable=False),
    Column("sheet_name", Text),
    Column("header_row", Integer),
    Column("talent_count", Integer, nullable=False, default=0, server_default="0"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

talents = Table(
    "talents",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=True, index=True),
    Column("version_id", Integer, ForeignKey("ratecard_versions.id"), nullable=False, index=True),
    Column("unique_key", Text, nullable=False, index=True),
    Column("nickname", Text, index=True),
    Column("account_id", Text, index=True),
    Column("blogger_id", Text),
    Column("homepage", Text),
    Column("data_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=True, index=True),
    Column("brand_name", Text),
    Column("filename", Text, nullable=False),
    Column("template_path", Text, nullable=False),
    Column("sheet_name", Text, nullable=False),
    Column("header_row", Integer, nullable=False),
    Column("columns_json", Text, nullable=False),
    Column("rows_json", Text, nullable=False),
    Column("missing_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
)


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.engine = self._create_engine(url or database_url())
        self.init()

    def _create_engine(self, url: str) -> Engine:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        return create_engine(url, future=True, connect_args=connect_args)

    def init(self) -> None:
        metadata.create_all(self.engine)
        self._migrate_existing_schema()

    def _migrate_existing_schema(self) -> None:
        inspector = inspect(self.engine)
        for table_name in ("ratecard_versions", "talents", "tasks"):
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            if "user_id" in existing:
                continue
            with self.engine.begin() as conn:
                conn.execute(text(f"alter table {table_name} add column user_id integer"))

    def create_user(self, username: str, password_hash: str) -> dict[str, Any]:
        normalized = username.strip().lower()
        with self.engine.begin() as conn:
            result = conn.execute(users.insert().values(username=normalized, password_hash=password_hash))
            user_id = int(result.inserted_primary_key[0])
            row = conn.execute(select(users).where(users.c.id == user_id)).mappings().one()
            user_count = conn.execute(select(func.count()).select_from(users)).scalar_one()
            if user_count == 1:
                self._claim_legacy_rows(conn, user_id)
        return self._user_from_row(row)

    def _claim_legacy_rows(self, conn: Any, user_id: int) -> None:
        for table in (ratecard_versions, talents, tasks):
            conn.execute(update(table).where(table.c.user_id.is_(None)).values(user_id=user_id))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        normalized = username.strip().lower()
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.username == normalized)).mappings().first()
        return self._user_from_row(row) if row else None

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
        return self._user_from_row(row) if row else None

    def latest_ratecard_version_id(self, user_id: int) -> int | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(ratecard_versions.c.id)
                .where(ratecard_versions.c.user_id == user_id)
                .order_by(desc(ratecard_versions.c.id))
                .limit(1)
            ).first()
        return int(row[0]) if row else None

    def latest_ratecard_version(self, user_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(
                    ratecard_versions.c.id,
                    ratecard_versions.c.filename,
                    ratecard_versions.c.sheet_name,
                    ratecard_versions.c.header_row,
                    ratecard_versions.c.talent_count,
                    ratecard_versions.c.created_at,
                )
                .where(ratecard_versions.c.user_id == user_id)
                .order_by(desc(ratecard_versions.c.id))
                .limit(1)
            ).mappings().first()
        return self._dict_from_row(row) if row else None

    def create_ratecard_version(
        self, user_id: int, filename: str, stored_path: str, sheet_name: str, header_row: int, talent_rows: list[dict[str, Any]]
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                ratecard_versions.insert().values(
                    user_id=user_id,
                    filename=filename,
                    stored_path=stored_path,
                    sheet_name=sheet_name,
                    header_row=header_row,
                    talent_count=len(talent_rows),
                )
            )
            version_id = int(result.inserted_primary_key[0])
            if talent_rows:
                conn.execute(
                    talents.insert(),
                    [
                        {
                            "user_id": user_id,
                            "version_id": version_id,
                            "unique_key": talent["unique_key"],
                            "nickname": talent.get("nickname"),
                            "account_id": talent.get("account_id"),
                            "blogger_id": talent.get("blogger_id"),
                            "homepage": talent.get("homepage"),
                            "data_json": dumps(talent["data"]),
                        }
                        for talent in talent_rows
                    ],
                )
        return version_id

    def search_talents(self, user_id: int, query: str, limit: int = 20) -> list[dict[str, Any]]:
        version_id = self.latest_ratecard_version_id(user_id)
        if not version_id:
            return []
        cleaned = query.strip()
        like = f"%{cleaned}%"
        priority = case(
            (talents.c.unique_key == cleaned, 0),
            (talents.c.account_id == cleaned, 1),
            (talents.c.blogger_id == cleaned, 2),
            (talents.c.nickname == cleaned, 3),
            else_=4,
        )
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(talents)
                .where(
                    and_(
                        talents.c.user_id == user_id,
                        talents.c.version_id == version_id,
                        or_(
                            talents.c.unique_key.like(like),
                            talents.c.nickname.like(like),
                            talents.c.account_id.like(like),
                            talents.c.blogger_id.like(like),
                            talents.c.homepage.like(like),
                        ),
                    )
                )
                .order_by(priority, talents.c.id.asc())
                .limit(limit)
            ).mappings().all()
        return [self._talent_from_row(row) for row in rows]

    def get_talent(self, user_id: int, talent_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(talents).where(and_(talents.c.id == talent_id, talents.c.user_id == user_id))
            ).mappings().first()
        return self._talent_from_row(row) if row else None

    def create_task(self, user_id: int, task: dict[str, Any]) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                tasks.insert().values(
                    user_id=user_id,
                    brand_name=task.get("brand_name"),
                    filename=task["filename"],
                    template_path=task["template_path"],
                    sheet_name=task["sheet_name"],
                    header_row=task["header_row"],
                    columns_json=dumps(task["columns"]),
                    rows_json=dumps(task["rows"]),
                    missing_json=dumps(task.get("missing", {})),
                )
            )
            return int(result.inserted_primary_key[0])

    def list_tasks(self, user_id: int) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    tasks.c.id,
                    tasks.c.brand_name,
                    tasks.c.filename,
                    tasks.c.sheet_name,
                    tasks.c.header_row,
                    tasks.c.created_at,
                    tasks.c.updated_at,
                )
                .where(tasks.c.user_id == user_id)
                .order_by(desc(tasks.c.id))
            ).mappings().all()
        return [self._dict_from_row(row) for row in rows]

    def get_task(self, user_id: int, task_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(tasks).where(and_(tasks.c.id == task_id, tasks.c.user_id == user_id))).mappings().first()
        if not row:
            return None
        task = self._dict_from_row(row)
        task["columns"] = loads(task.pop("columns_json"), [])
        task["rows"] = loads(task.pop("rows_json"), [])
        task["missing"] = loads(task.pop("missing_json"), {})
        return task

    def save_task_rows(self, user_id: int, task_id: int, rows: list[dict[str, Any]], missing: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(tasks)
                .where(and_(tasks.c.id == task_id, tasks.c.user_id == user_id))
                .values(rows_json=dumps(rows), missing_json=dumps(missing), updated_at=func.now())
            )

    def _user_from_row(self, row: RowMapping) -> dict[str, Any]:
        return self._dict_from_row(row)

    def _talent_from_row(self, row: RowMapping) -> dict[str, Any]:
        talent = self._dict_from_row(row)
        talent["data"] = loads(talent.pop("data_json"), {})
        return talent

    def _dict_from_row(self, row: RowMapping) -> dict[str, Any]:
        result = dict(row)
        for key, value in result.items():
            if hasattr(value, "isoformat"):
                result[key] = value.isoformat(sep=" ")
        return result

