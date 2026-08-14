from typing import AsyncGenerator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.core.security import decodificar_token
from app.models.usuario import Usuario, RolUsuario
from sqlalchemy import select

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_usuario_actual(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    credenciales_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decodificar_token(token)
    if payload is None:
        raise credenciales_exc

    usuario_id: int = payload.get("sub")
    if usuario_id is None:
        raise credenciales_exc

    result = await db.execute(select(Usuario).where(Usuario.id == int(usuario_id)))
    usuario = result.scalar_one_or_none()
    if usuario is None or not usuario.activo:
        raise credenciales_exc
    return usuario


async def require_bibliotecario(
    usuario: Usuario = Depends(get_usuario_actual),
) -> Usuario:
    if usuario.rol not in (RolUsuario.BIBLIOTECARIO, RolUsuario.ADMINISTRADOR):
        raise HTTPException(status_code=403, detail="Se requiere rol de bibliotecario")
    return usuario


async def require_administrador(
    usuario: Usuario = Depends(get_usuario_actual),
) -> Usuario:
    if usuario.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Se requiere rol de administrador")
    return usuario
