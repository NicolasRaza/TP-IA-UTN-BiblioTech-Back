"""Entorno de pruebas: la app real sobre SQLite en memoria.

Se levanta el `main.app` tal cual corre en producción y sólo se reemplaza la
base: así un test verde dice algo sobre la API que se despliega, y no sobre una
maqueta paralela. La única concesión es el motor —SQLite en vez de Postgres—,
que alcanza para lo que estos tests verifican: contratos, permisos y
persistencia.
"""

import os
from datetime import date

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.deps import get_db  # noqa: E402
from app.core.security import crear_access_token, hashear_password  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.models import circulacion, libro, sistema, usuario  # noqa: F401,E402
from app.models.usuario import (  # noqa: E402
    CategoriaLector,
    EstadoUsuario,
    Lector,
    RolUsuario,
    Usuario,
)
from main import app  # noqa: E402


@pytest_asyncio.fixture
async def sesion_bd():
    # Cada test estrena base: una sola conexión compartida sobre SQLite en
    # memoria, para que las tablas creadas acá sean las que ve la app.
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    fabrica = async_sessionmaker(engine, expire_on_commit=False)
    yield fabrica
    await engine.dispose()


@pytest_asyncio.fixture
async def datos(sesion_bd):
    """Un administrador, un bibliotecario y dos lectores activos."""
    async with sesion_bd() as db:
        admin = Usuario(email="admin@t.com", password_hash=hashear_password("x"),
                        rol=RolUsuario.ADMINISTRADOR)
        biblio = Usuario(email="biblio@t.com", password_hash=hashear_password("x"),
                         rol=RolUsuario.BIBLIOTECARIO)
        u_lector = Usuario(email="lector@t.com", password_hash=hashear_password("x"),
                           rol=RolUsuario.LECTOR)
        u_otro = Usuario(email="otro@t.com", password_hash=hashear_password("x"),
                         rol=RolUsuario.LECTOR)
        db.add_all([admin, biblio, u_lector, u_otro])
        await db.flush()

        lector = Lector(usuario_id=u_lector.id, nombre="Laura", apellido="Méndez",
                        documento="33456789", fecha_nacimiento=date(1990, 1, 1),
                        categoria=CategoriaLector.ADULTO, estado=EstadoUsuario.ACTIVO,
                        consentimiento_datos=True)
        otro = Lector(usuario_id=u_otro.id, nombre="Otro", apellido="Lector",
                      documento="40000000", fecha_nacimiento=date(1990, 1, 1),
                      categoria=CategoriaLector.ADULTO, estado=EstadoUsuario.ACTIVO,
                      consentimiento_datos=True)
        db.add_all([lector, otro])
        await db.commit()

        return {
            "admin": _auth(admin.id),
            "biblio": _auth(biblio.id),
            "lector": _auth(u_lector.id),
            "otro": _auth(u_otro.id),
            "lector_id": lector.id,
            "otro_id": otro.id,
            "sesion": sesion_bd,
        }


def _auth(usuario_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {crear_access_token({'sub': str(usuario_id)})}"}


@pytest_asyncio.fixture
async def cliente(sesion_bd):
    async def _get_db():
        async with sesion_bd() as sesion:
            yield sesion

    app.dependency_overrides[get_db] = _get_db
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def base_url() -> str:
    return "/api/v1"
