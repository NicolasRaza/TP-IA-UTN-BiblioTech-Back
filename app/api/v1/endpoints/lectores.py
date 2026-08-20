from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.deps import get_db, get_usuario_actual, require_bibliotecario
from app.core.security import hashear_password
from app.models.usuario import Lector, Usuario, EstadoUsuario, RolUsuario
from app.models.circulacion import Prestamo, EstadoPrestamo, Multa, EstadoMulta
from app.schemas.usuario import LectorCreate, LectorUpdate, LectorResponse, LectorFichaResponse

router = APIRouter(prefix="/lectores", tags=["Lectores"])


@router.post("/", response_model=LectorResponse, status_code=201,
             summary="Autorregistro de lector (público, pendiente de verificación)")
async def crear_lector(
    data: LectorCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint público (no requiere token): cualquier persona puede cargar sus
    datos desde la pantalla de registro. Crea un lector y un usuario asociado
    con rol LECTOR, siempre en estado SUSPENDIDO.

    Un bibliotecario debe verificarlo y pasarlo a ACTIVO (PATCH /lectores/{id}
    con {"estado": "activo"}) antes de que pueda sacar préstamos o reservar.
    Mientras tanto puede iniciar sesión y navegar el catálogo, pero
    `verificar_lector_habilitado` le va a bloquear cualquier operación de
    circulación.

    Si el lector es menor de edad, los campos tutor_nombre y tutor_telefono son obligatorios.
    """
    # Verificar unicidad de documento
    existe = await db.execute(select(Lector).where(Lector.documento == data.documento))
    if existe.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ya existe un lector con ese documento")

    # Validar tutor para menores
    edad = (date.today() - data.fecha_nacimiento).days // 365
    if edad < 18 and not data.tutor_nombre:
        raise HTTPException(status_code=422, detail="Los menores de edad requieren datos del tutor")

    # Crear usuario de app
    usuario = Usuario(
        email=data.email,
        password_hash=hashear_password(data.documento),  # contraseña inicial = documento
        rol=RolUsuario.LECTOR,
    )
    db.add(usuario)
    await db.flush()

    lector = Lector(
        usuario_id=usuario.id,
        nombre=data.nombre,
        apellido=data.apellido,
        documento=data.documento,
        fecha_nacimiento=data.fecha_nacimiento,
        telefono=data.telefono,
        domicilio=data.domicilio,
        categoria=data.categoria,
        estado=EstadoUsuario.PENDIENTE,  # era SUSPENDIDO
        tutor_nombre=data.tutor_nombre,
        tutor_telefono=data.tutor_telefono,
        consentimiento_datos=data.consentimiento_datos,
    )
    db.add(lector)
    await db.commit()
    await db.refresh(lector)
    return lector


@router.get("/", response_model=list[LectorResponse], summary="Listar lectores")
async def listar_lectores(
    nombre: str | None = Query(None, description="Filtrar por nombre o apellido"),
    documento: str | None = Query(None),
    estado: EstadoUsuario | None = Query(
        None, description="Filtrar por estado. Usar 'pendiente' para ver autorregistros sin verificar, 'suspendido' para lectores con mora o multas."
    ),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    query = select(Lector)
    if nombre:
        query = query.where(
            (Lector.nombre.ilike(f"%{nombre}%")) | (Lector.apellido.ilike(f"%{nombre}%"))
        )
    if documento:
        query = query.where(Lector.documento.ilike(f"%{documento}%"))
    if estado:
        query = query.where(Lector.estado == estado)

    result = await db.execute(query.order_by(Lector.apellido))
    return result.scalars().all()


@router.get("/{lector_id}", response_model=LectorFichaResponse, summary="Ficha de lector")
async def obtener_lector(
    lector_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lector).where(Lector.id == lector_id))
    lector = result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Lector no encontrado")

    # Contar préstamos activos
    prestamos_q = await db.execute(
        select(func.count()).where(
            Prestamo.lector_id == lector_id,
            Prestamo.estado == EstadoPrestamo.ACTIVO,
        )
    )
    multas_q = await db.execute(
        select(func.count()).where(
            Multa.lector_id == lector_id,
            Multa.estado == EstadoMulta.PENDIENTE,
        )
    )
    ficha = LectorFichaResponse.model_validate(lector)
    ficha.prestamos_activos = prestamos_q.scalar()
    ficha.multas_pendientes = multas_q.scalar()
    return ficha


@router.get("/{lector_id}/elegibilidad", summary="Evaluar elegibilidad de lector (AgenteEvaluador)")
async def evaluar_elegibilidad(
    lector_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Evalúa mediante el AgenteEvaluador si el lector está habilitado para solicitar o reservar libros:
    - Cuenta activa
    - Sin multas pendientes
    - Sin préstamos con fecha de vencimiento superada
    - Cupo disponible según categoría
    """
    from app.agents.agente_evaluador import AgenteEvaluador
    from app.agents.repositorios_impl import construir_repositorio

    repo = construir_repositorio(db)
    evaluador = AgenteEvaluador(repo)
    return await evaluador.evaluar_elegibilidad_lector(str(lector_id))


@router.patch("/{lector_id}", response_model=LectorResponse, summary="Modificar lector")
async def modificar_lector(
    lector_id: int,
    data: LectorUpdate,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lector).where(Lector.id == lector_id))
    lector = result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Lector no encontrado")

    for campo, valor in data.model_dump(exclude_none=True).items():
        setattr(lector, campo, valor)

    await db.commit()
    await db.refresh(lector)
    return lector


@router.delete("/{lector_id}", summary="Baja lógica de lector")
async def baja_lector(
    lector_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Baja lógica: no se elimina el registro ni el historial.
    No se puede dar de baja si el lector tiene préstamos activos.
    """
    result = await db.execute(select(Lector).where(Lector.id == lector_id))
    lector = result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Lector no encontrado")

    activos = await db.execute(
        select(func.count()).where(
            Prestamo.lector_id == lector_id,
            Prestamo.estado == EstadoPrestamo.ACTIVO,
        )
    )
    if activos.scalar() > 0:
        raise HTTPException(
            status_code=409,
            detail="El lector tiene préstamos activos. Debe devolverlos antes de la baja.",
        )

    lector.estado = EstadoUsuario.BAJA
    await db.commit()
    return {"mensaje": "Lector dado de baja correctamente"}


@router.post("/{lector_id}/reactivar", summary="Reactivar lector dado de baja")
async def reactivar_lector(
    lector_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lector).where(Lector.id == lector_id))
    lector = result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Lector no encontrado")

    lector.estado = EstadoUsuario.ACTIVO
    await db.commit()
    return {"mensaje": "Lector reactivado"}
