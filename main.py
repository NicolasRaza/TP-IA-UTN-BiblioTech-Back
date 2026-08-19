import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import api_router
from app.db.session import engine, Base
from app.agents.planner import agente_planificador

# Importar todos los modelos para que Alembic y Base los detecte
from app.models import usuario, libro, circulacion  # noqa: F401

logger = logging.getLogger(__name__)


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

# El orden de estos dos middlewares importa y no es intercambiable: Starlette
# construye la pila con el primero agregado como el más interno, así que este
# bloque deja el CORS por fuera del manejo de errores.
#
# Sin esta capa, una excepción no capturada sube hasta el `ServerErrorMiddleware`
# de Starlette, que vive por *encima* del CORSMiddleware y responde un 500 pelado
# sin `Access-Control-Allow-Origin`. El browser entonces descarta la respuesta y
# reporta "CORS Missing Allow Origin", escondiendo el error real: se pierde el
# status, el detalle y el stack trace, y el bug parece de configuración de CORS
# cuando en realidad es del servidor. Atrapándola acá adentro, el 500 sale por
# el CORSMiddleware, llega al cliente con sus headers y se ve por lo que es.
@app.middleware("http")
async def errores_no_manejados(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Error no manejado en %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor"},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, reemplazar con el dominio de Flutter
    # Con `allow_origins=["*"]`, la spec de CORS prohíbe las credenciales: el
    # browser rechaza toda respuesta que combine el comodín con
    # `Allow-Credentials: true`. La app no las necesita —autentica con el header
    # `Authorization: Bearer`, no con cookies—, así que va en False.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "sistema": "SGB v1.0"}
