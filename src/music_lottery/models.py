import json
from typing import Any, Literal
import uuid

from pydantic import BaseModel, field_serializer, field_validator
from pydantic import Field as PydField
from sqlmodel import Field, SQLModel


class MusicMeta(SQLModel):
    title: str | None = None
    album: str | None = None
    artists: str = "[]"
    albumartists: str = "[]"
    duration: float = 0


class MusicLibItem(MusicMeta, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    path: str = Field(unique=True)
    last_update: float


class AccessSession(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    music_id: uuid.UUID
    expires: float  # 时间戳


class MusicResp(BaseModel):
    id: uuid.UUID
    title: str | None
    album: str | None
    artists: list[str]
    albumartists: list[str]
    duration: float = 0
    filename: str
    session: uuid.UUID
    href: str

    @field_validator("artists", "albumartists", mode="before")
    @classmethod
    def vali(cls, val):
        return json.loads(val)


class ConfigModel(BaseModel):
    musiclib_location: str
    access_token: str  # 用于申请音乐库分享
    default_expires: int = PydField(60 * 30, gt=0)  # 分享过期用时(s)
    scan_interval: int = PydField(
        60 * 60 * 24, ge=0
    )  # 扫描音乐库间隔时间(s)，设为 0 为手动扫描
    artists_split: list[str] = ["/", ";", ","]
    artists_dont_split: list[str] = []


class StatusResp(BaseModel):
    status: Literal["pause", "running"]
    count: int
    online: float
    time: float
