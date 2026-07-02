import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    yield TestingSessionLocal

    engine.dispose()
    os.remove(path)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_headers(workspace_id="ws_1", user_id="usr_1", scopes=None):
    if scopes is None:
        scopes = ["approval:read", "approval:create", "approval:decide", "approval:cancel"]
    return {
        "X-Workspace-Id": workspace_id,
        "X-User-Id": user_id,
        "X-Scopes": ",".join(scopes),
    }
