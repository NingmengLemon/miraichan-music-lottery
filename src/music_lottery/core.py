import logging
import time
from typing import Annotated
import uuid
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlmodel import create_engine, Session, select, SQLModel, func
from apscheduler.schedulers.background import BackgroundScheduler

from .models import (
    MusicLibItem,
    MusicResp,
    AccessSession,
    ConfigModel,
)
from .utils import RWContext
from .musiclib import MetadataReader, walk_all_musicfiles


app = FastAPI()
logger = logging.getLogger(__name__)

db_filename = "musiclib.db"
db_url = f"sqlite:///{db_filename}"

db_engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False},
)
db_lock = RWContext()


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


def scan_update_musiclib():
    location = os.path.normpath(config.musiclib_location)
    sfiles = walk_all_musicfiles(location)
    to_add = set[str]()
    to_update = set[str]()
    to_delete = set[str]()
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
        for path in to_update:
            item = dbsession.exec(
                select(MusicLibItem).where(MusicLibItem.path == path)
            ).one()
            for k, v in metareader.read_metadata(path).model_dump().items():
                setattr(item, k, v)
            dbsession.add(item)
            dbsession.commit()
            dbsession.refresh(item)
        if to_delete:
            for path in to_delete:
                item = dbsession.exec(
                    select(MusicLibItem).where(MusicLibItem.path == path)
                ).one()
                dbsession.delete(item)
            dbsession.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        clear_expired_session, "interval", minutes=config.default_expires / 60
    )
    scheduler.add_job(
        clear_expired_session, "interval", minutes=config.default_expires / 60
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


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


async def verify_token(access_token: str = Query()):
    if access_token != config.access_token:
        raise HTTPException(403, "不是哥们，你的 token 呢，让咱康康！")
    return access_token


AcTokenDep = Annotated[str, Depends(verify_token)]


@app.get("/draw")
async def share(
    dbsession: DbSessDep,
    _: AcTokenDep,
    request: Request,
    expires: int = Query(
        default=config.default_expires,
        ge=30,
        le=60 * 60 * 24,
    ),
):
    if item := dbsession.exec(
        select(MusicLibItem).order_by(func.random()).limit(1)  # pylint: disable=E1102
    ).one_or_none():
        session_id = uuid.uuid4()
        session = AccessSession(
            id=session_id, music_id=item.id, expires=time.time() + expires
        )
        dbsession.add(session)
        dbsession.commit()
        return MusicResp.model_validate(
            item,
            update={
                "session": session_id,
                "url": f"http://{request.client.host}/get?session={str(session_id)}",
            },
        )
    raise HTTPException(503, "哇呜，音乐库中没有可用的内容")


@app.get("/get")
async def get(dbsession: DbSessDep, session: AcSessDep):
    music_id = session.music_id
    if item := dbsession.exec(
        select(MusicLibItem).where(MusicLibItem.id == music_id)
    ).one_or_none():
        path = item.path
        if os.path.exists(path):
            return FileResponse(path, filename=os.path.split(item.path)[1])
    raise HTTPException(404, "你的会话没有过期，但是文件找不到了，怎么秽蚀呢")
