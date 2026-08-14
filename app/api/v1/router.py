from fastapi import APIRouter
from app.api.v1.endpoints import auth, lectores, catalogo, circulacion

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(lectores.router)
api_router.include_router(catalogo.router)
api_router.include_router(circulacion.router)
