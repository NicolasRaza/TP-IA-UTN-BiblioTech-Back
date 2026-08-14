from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.db.session import engine, Base
from app.agents.planner import agente_planificador

# Importar todos los modelos para que Alembic y Base los detecte
from app.models import usuario, libro, circulacion  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arranque: crear tablas y lanzar el scheduler del Agente Planificador
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    agente_planificador.iniciar()
    yield
    # Apagado
    agente_planificador.detener()


app = FastAPI(
    title="Sistema de Gestión de Bibliotecas (SGB)",
    description="""
API REST para la gestión integral de bibliotecas públicas, escolares e institucionales.

## Pilares
- **Lectores**: alta, baja, modificación y ficha completa con historial.
- **Catálogo**: carga de libros asistida por OCR + enriquecimiento por ISBN, gestión de ejemplares y QR.
- **Circulación**: préstamos por QR, reservas con cola, devoluciones, multas y notificaciones automáticas.

## Autenticación
Todas las rutas requieren un JWT obtenido en `/api/v1/auth/login`.
Los roles disponibles son: `lector`, `bibliotecario` y `administrador`.
    """,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, reemplazar con el dominio de Flutter
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "sistema": "SGB v1.0"}
