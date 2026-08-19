from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.deps import get_db, require_administrador
from app.core.security import hashear_password
from app.models.usuario import Usuario, RolUsuario
from app.schemas.usuario import BibliotecarioCreate, BibliotecarioUpdate, BibliotecarioResponse

router = APIRouter(prefix="/usuarios", tags=["Usuarios internos"])


@router.post("/", response_model=BibliotecarioResponse, status_code=201,
             summary="Alta de bibliotecario (solo administrador)")
async def crear_bibliotecario(
    data: BibliotecarioCreate,
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    """
    Crea un usuario interno con rol bibliotecario (o administrador).
    No crea Lector: es exclusivo para personal de la biblioteca.
    """
    existe = await db.execute(select(Usuario).where(Usuario.email == data.email))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")

    usuario = Usuario(
        email=data.email,
        password_hash=hashear_password(data.password),
        rol=data.rol,
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.get("/", response_model=list[BibliotecarioResponse],
            summary="Listar bibliotecarios y administradores")
async def listar_bibliotecarios(
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Usuario)
        .where(Usuario.rol.in_([RolUsuario.BIBLIOTECARIO, RolUsuario.ADMINISTRADOR]))
        .order_by(Usuario.email)
    )
    return result.scalars().all()


@router.get("/{usuario_id}", response_model=BibliotecarioResponse,
            summary="Detalle de bibliotecario")
async def obtener_bibliotecario(
    usuario_id: int,
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    usuario = await _buscar_bibliotecario_o_404(usuario_id, db)
    return usuario


@router.patch("/{usuario_id}", response_model=BibliotecarioResponse,
              summary="Modificar bibliotecario")
async def modificar_bibliotecario(
    usuario_id: int,
    data: BibliotecarioUpdate,
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    usuario = await _buscar_bibliotecario_o_404(usuario_id, db)

    datos = data.model_dump(exclude_none=True)
    if "password" in datos:
        usuario.password_hash = hashear_password(datos.pop("password"))
    for campo, valor in datos.items():
        setattr(usuario, campo, valor)

    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", summary="Baja lógica de bibliotecario")
async def baja_bibliotecario(
    usuario_id: int,
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    """
    Baja lógica: desactiva el usuario (activo=False) en vez de borrarlo,
    igual que se hace con los lectores.
    """
    usuario = await _buscar_bibliotecario_o_404(usuario_id, db)
    usuario.activo = False
    await db.commit()
    return {"mensaje": "Bibliotecario dado de baja correctamente"}


@router.post("/{usuario_id}/reactivar", summary="Reactivar bibliotecario dado de baja")
async def reactivar_bibliotecario(
    usuario_id: int,
    _: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    usuario = await _buscar_bibliotecario_o_404(usuario_id, db)
    usuario.activo = True
    await db.commit()
    return {"mensaje": "Bibliotecario reactivado"}


async def _buscar_bibliotecario_o_404(usuario_id: int, db: AsyncSession) -> Usuario:
    result = await db.execute(select(Usuario).where(Usuario.id == usuario_id))
    usuario = result.scalar_one_or_none()
    if not usuario or usuario.rol == RolUsuario.LECTOR:
        raise HTTPException(status_code=404, detail="Bibliotecario no encontrado")
    return usuario
