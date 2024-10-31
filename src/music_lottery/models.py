from typing import Any
import uuid

from pydantic import BaseModel
from pydantic import Field as PydField
from sqlmodel import Field, SQLModel


class MusicMeta(SQLModel):
    title: str
    artists: list[str] = []
    album: str | None = ""
    albumartists: list[str] = []
    cover: bytes | None = b""
    extra: dict[str, Any] = {}


class UsePrimaryKeyUUID(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class MusicLibItem(UsePrimaryKeyUUID, MusicMeta, table=True):
    path: str = Field(unique=True)
    last_update: float


class AccessSession(UsePrimaryKeyUUID, SQLModel, table=True):
    music_id: uuid.UUID
    expires: float  # 时间戳


class MusicResp(MusicMeta):
    filename: str
    session: uuid.UUID
    url: str


class ConfigModel(BaseModel):
    musiclib_location: str
    access_token: str  # 用于申请音乐库分享
    default_expires: int = PydField(60 * 5, lt=0)  # 分享过期用时(s)
    scan_interval: int = PydField(0, le=0)  # 扫描音乐库间隔时间(s)，设为 0 为手动扫描
    artists_split: str = "/"
    artists_dont_split: list[str] = []
