from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.deps import get_db, get_usuario_actual
from app.core.security import verificar_password, crear_access_token, hashear_password
from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import LoginRequest, TokenResponse, FirebaseTokenUpdate

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Devuelve un JWT para autenticar las siguientes peticiones.
    El rol del usuario (lector / bibliotecario / administrador) queda incluido en el token.
    """
    result = await db.execute(select(Usuario).where(Usuario.email == data.email))
    usuario = result.scalar_one_or_none()

    if not usuario or not verificar_password(data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )
    if not usuario.activo:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    token = crear_access_token({"sub": str(usuario.id), "rol": usuario.rol})
    return TokenResponse(access_token=token, token_type="bearer", rol=usuario.rol)


@router.post("/firebase-token", summary="Registrar token de notificaciones push")
async def registrar_firebase_token(
    data: FirebaseTokenUpdate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """
    La app Flutter envía el FCM token al iniciar sesión.
    El Agente Planificador lo usa para enviar notificaciones push.
    """
    usuario.firebase_token = data.firebase_token
    await db.commit()
    return {"mensaje": "Token registrado correctamente"}


@router.get("/me", summary="Datos del usuario autenticado")
async def mi_perfil(usuario: Usuario = Depends(get_usuario_actual)):
    return {
        "id": usuario.id,
        "email": usuario.email,
        "rol": usuario.rol,
        "lector_id": usuario.lector.id if usuario.lector else None,
        "estado": usuario.lector.estado if usuario.lector else None
    }
