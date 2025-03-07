import asyncio
import logging
import threading
import time
from typing import Annotated
import uuid
from contextlib import asynccontextmanager, contextmanager
import posixpath
import re

from fastapi import FastAPI, HTTPException, Depends, Query, Header
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
import filetype
from sqlmodel import create_engine, Session, select, SQLModel, func, col
from apscheduler.schedulers.background import BackgroundScheduler

from tinytag import TinyTag

from .models import (
    MetadataResp,
    MusicLibItem,
    MusicResp,
    AccessSession,
    ConfigModel,
    ScanResultResp,
    StatusResp,
)
from .utils import with_lock
from .musiclib import MetadataReader, walk_all_musicfiles

INIT_TIME = time.time()

logger = logging.getLogger(__name__)

db_filename = "musiclib.db"
db_url = f"sqlite:///{db_filename}"

db_engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False},
)
db_scanlock = threading.Lock()
pause_event = threading.Event()
# pause_event.clear()


def load_config(location: str = "config.json"):
    with open(location, "rb") as fp:
        return ConfigModel.model_validate_json(fp.read())


config = load_config()
metareader = MetadataReader(config)


def create_db_and_tables():
    SQLModel.metadata.create_all(db_engine)


def get_dbsession():
    with Session(db_engine) as session:
        yield session


DbSessDep = Annotated[Session, Depends(get_dbsession)]


def clear_expired_session():
    with Session(db_engine) as dbsession:
        sesss = dbsession.exec(
            select(AccessSession).where(AccessSession.expires <= time.time())
        ).all()
        if sesss:
            for s in sesss:
                dbsession.delete(s)
            dbsession.commit()
            logger.info("cleared %d expired sessions", len(sesss))


@with_lock(db_scanlock)
def scan_update_musiclib():
    # if pause_event.is_set():
    #     logger.info("Skip scan due to maintenance")
    #     return
    logger.info("Scanning music library...")
    location = posixpath.normpath(config.musiclib_location)
    sfiles = walk_all_musicfiles(location)
    to_add = set()
    to_update = set()
    to_delete = set()
    with Session(db_engine) as dbsession:
        dfiles = {
            i.path: i.last_update for i in dbsession.exec(select(MusicLibItem)).all()
        }
    for sfile, st in sfiles.items():
        if sfile in dfiles:
            if st > dfiles[sfile]:
                to_update.add(sfile)
        else:
            to_add.add(sfile)
    for dfile in dfiles.keys():
        if dfile not in sfiles:
            to_delete.add(dfile)
    with Session(db_engine) as dbsession:
        if to_add:
            for path in to_add:
                dbsession.add(
                    MusicLibItem.model_validate(
                        metareader.read_metadata(path),
                        update={"path": path, "last_update": time.time()},
                    )
                )
            dbsession.commit()
        logger.info("Added %s music records", len(to_add))
        for path in to_update:
            item = dbsession.exec(
                select(MusicLibItem).where(MusicLibItem.path == path)
            ).one()
            for k, v in metareader.read_metadata(path).model_dump().items():
                setattr(item, k, v)
            dbsession.add(item)
            dbsession.commit()
            dbsession.refresh(item)
        logger.info("Updated %s music records", len(to_update))
        if to_delete:
            for path in to_delete:
                item = dbsession.exec(
                    select(MusicLibItem).where(MusicLibItem.path == path)
                ).one()
                dbsession.delete(item)
            dbsession.commit()
        logger.info("Deleted %s music records", len(to_delete))
    return len(to_add), len(to_update), len(to_delete)


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    clear_expired_session()
    scan_update_musiclib()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        clear_expired_session, "interval", minutes=config.default_expires / 60
    )
    if config.scan_interval > 0:
        scheduler.add_job(
            scan_update_musiclib, "interval", minutes=config.scan_interval / 60
        )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="static/playerv2/assets"), "playerv2")


@app.get("/playerv2", response_class=HTMLResponse)
async def pv2index():
    return FileResponse("static/playerv2/index.html")


@app.get("/teapot")
async def teapot():
    raise HTTPException(status_code=418)


async def verify_session(dbsession: DbSessDep, session: uuid.UUID = Query()):
    if session:
        if sess := dbsession.exec(
            select(AccessSession).where(AccessSession.id == session)
        ).one_or_none():
            if sess.expires > time.time():
                return sess
            dbsession.delete(sess)
            dbsession.commit()
    raise HTTPException(status_code=403, detail="会话过期或者不存在，下次要早点来噢喵w")


AcSessDep = Annotated[AccessSession, Depends(verify_session)]


async def verify_token(authorization: str = Header("")):
    if len(_ := authorization.split(maxsplit=1)) == 2:
        token = _[1]
    elif _:
        token = _[0]
    else:
        raise HTTPException(403, "不是哥们，你 token 呢")
    if token.strip() != config.access_token:
        raise HTTPException(403, "不是哥们，你的 token 错辣")
    return authorization


AcTokenDep = Annotated[str, Depends(verify_token)]


async def check_pause():
    if pause_event.is_set():
        raise HTTPException(503, "暂停服务了喵，红豆泥私密马赛w")
    return "ok"


CkPauseDep = Annotated[str, Depends(check_pause)]


@app.get("/pause")
async def pause(_: AcTokenDep):
    pause_event.set()
    return "ok"


@app.get("/resume")
async def resume(_: AcTokenDep):
    pause_event.clear()
    return "ok"


@contextmanager
def with_event_set(event: threading.Event | asyncio.Event):
    event.set()
    try:
        yield
    finally:
        event.clear()


@app.get("/scan", response_model=ScanResultResp)
async def do_scan(_: AcTokenDep):
    with with_event_set(pause_event):
        a, u, d = await asyncio.to_thread(scan_update_musiclib)
    return ScanResultResp(add=a, update=u, delete=d)


@app.get("/status", response_model=StatusResp)
async def get_status(dbsession: DbSessDep, _: AcTokenDep):
    count = dbsession.exec(
        select(func.count()).select_from(MusicLibItem)  # pylint: disable=E1102
    ).one()
    return StatusResp(
        status=("pause" if pause_event.is_set() else "running"),
        count=count,
        online=time.time() - INIT_TIME,
        time=time.time(),
    )


def is_playerv2_available():
    return posixpath.exists("static/playerv2/index.html")


@app.get("/draw", response_model=MusicResp)
async def new_share(
    dbsession: DbSessDep,
    _: AcTokenDep,
    __: CkPauseDep,
    expires: int = Query(
        default=config.default_expires,
        ge=30,
        le=60 * 60 * 24,
    ),
    title: str = Query(default=""),
    album: str = Query(default=""),
    artist: str = Query(default=""),
):
    statement = select(MusicLibItem)
    title, album, artist = (
        title.strip(),
        album.strip(),
        re.sub(r"[\"\'\\\/\[\]\{\}]", "", artist.strip()),
    )
    if title:
        statement = statement.where(col(MusicLibItem.title).icontains(title))
    if album:
        statement = statement.where(col(MusicLibItem.album).icontains(album))
    if artist:
        statement = statement.where(col(MusicLibItem.artists).icontains(artist))
    if item := dbsession.exec(
        statement.order_by(func.random()).limit(1)  # pylint: disable=E1102
    ).one_or_none():
        session_id = uuid.uuid4()
        session = AccessSession(
            id=session_id, music_id=item.id, expires=time.time() + expires
        )
        dbsession.add(session)
        dbsession.commit()
        return MusicResp(
            id=item.id,
            title=item.title,
            album=item.album,
            artists=item.artists,
            albumartists=item.albumartists,
            duration=item.duration,
            session=session_id,
            href=f"/get?session={session_id}",
            player=f"/player{"v2" if is_playerv2_available() else ""}?session={session_id}",
            lyrics=(
                f"/lyrics?session={session_id}"
                if posixpath.exists(posixpath.splitext(item.path)[0] + ".lrc")
                else None
            ),
            filename=posixpath.split(item.path)[1],
        )
    raise HTTPException(503, "哇呜，音乐库中没有可用的内容")


@app.get("/get", response_class=FileResponse)
async def get_file(dbsession: DbSessDep, _: CkPauseDep, session: AcSessDep):
    music_id = session.music_id
    if item := dbsession.exec(
        select(MusicLibItem).where(MusicLibItem.id == music_id)
    ).one_or_none():
        path = item.path
        if posixpath.exists(path):
            return FileResponse(path, filename=posixpath.split(item.path)[1])
    raise HTTPException(404, "你的会话没有过期，只是文件找不到了，怎么秽蚀呢qwq")


@app.get("/image", response_class=FileResponse)
async def get_cover(dbsession: DbSessDep, _: CkPauseDep, session: AcSessDep):
    if item := dbsession.exec(
        select(MusicLibItem).where(MusicLibItem.id == session.music_id)
    ).one_or_none():
        path = item.path
        if posixpath.exists(path):
            tag = TinyTag.get(path, image=True, duration=False)
            if img := tag.images.any:
                return Response(
                    img.data,
                    media_type=filetype.guess_mime(img.data) or "image/octet-stream",
                )
    raise HTTPException(404, "你的会话没有过期，只是文件找不到了，怎么秽蚀呢qwq")


@app.get("/lyrics", response_class=PlainTextResponse)
async def get_lyrics(dbsession: DbSessDep, _: CkPauseDep, session: AcSessDep):
    music_id = session.music_id
    if item := dbsession.exec(
        select(MusicLibItem).where(MusicLibItem.id == music_id)
    ).one_or_none():
        path = item.path
        lrc_path = posixpath.splitext(path)[0] + ".lrc"
        if posixpath.exists(lrc_path):
            return FileResponse(lrc_path)
    raise HTTPException(404, "未找到歌词文件")


@app.get("/metadata", response_model=MetadataResp)
async def get_metadata(dbsession: DbSessDep, _: CkPauseDep, session: AcSessDep):
    music_id = session.music_id
    if item := dbsession.exec(
        select(MusicLibItem).where(MusicLibItem.id == music_id)
    ).one_or_none():
        path = item.path
        if posixpath.exists(path):
            raw = TinyTag.get(path).as_dict()
            return MetadataResp(
                title=item.title,
                album=item.album,
                artists=item.artists,
                albumartists=item.albumartists,
                track=raw.get("track"),
                #
                duration=item.duration,
                filesize=raw.get("filesize") or posixpath.getsize(path),
                bitrate=raw.get("bitrate", 0.0),
                samplerate=raw.get("samplerate", 0),
                filename=posixpath.basename(path),
            )
    raise HTTPException(404, "未找到音乐文件")


@app.get("/player", response_class=HTMLResponse)
async def get_player(_: CkPauseDep):
    return FileResponse("src/player.html")
