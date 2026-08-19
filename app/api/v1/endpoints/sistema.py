"""Notificaciones, auditoría, parámetros de la biblioteca y aprendizaje.

Las cuatro features que hasta ahora vivían en el almacenamiento del navegador
de cada cliente. Están juntas porque comparten la misma naturaleza —son
transversales a los tres pilares y ninguna es un agregado de negocio propio— y
porque las cuatro se resuelven con lecturas y escrituras directas, sin las
reglas de circulación que justifican el tamaño de `circulacion.py`.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    get_db,
    get_usuario_actual,
    require_administrador,
    require_bibliotecario,
)
from app.models.sistema import (
    ConfiguracionBiblioteca,
    CorreccionAprendizaje,
    EventoAuditoria,
    InteraccionAprendizaje,
    Notificacion,
)
from app.models.usuario import Lector, RolUsuario, Usuario
from app.schemas.sistema import (
    ConfiguracionResponse,
    ConfiguracionUpdate,
    CorreccionCreate,
    CorreccionResponse,
    EventoAuditoriaCreate,
    EventoAuditoriaResponse,
    InteraccionCreate,
    InteraccionResponse,
    NotificacionCreate,
    NotificacionResponse,
)

router = APIRouter(tags=["Sistema"])


async def _lector_id_de(usuario: Usuario, db: AsyncSession) -> int | None:
    """El lector asociado a un usuario, o None si es personal."""
    if usuario.rol != RolUsuario.LECTOR:
        return None
    result = await db.execute(select(Lector).where(Lector.usuario_id == usuario.id))
    lector = result.scalar_one_or_none()
    return lector.id if lector else None


async def _resolver_destinatario(
    lector_id: int | None,
    usuario: Usuario,
    db: AsyncSession,
) -> int:
    """De quién son las notificaciones que se están pidiendo o marcando.

    Un lector sólo puede operar sobre las suyas: pedir las de otro es un 403 y
    no un listado vacío, porque un vacío se confunde con "no tenés avisos" y
    esconde el error de permisos.
    """
    propio = await _lector_id_de(usuario, db)
    if propio is not None:
        if lector_id is not None and lector_id != propio:
            raise HTTPException(
                status_code=403, detail="Sólo podés ver tus propias notificaciones"
            )
        return propio

    if lector_id is None:
        raise HTTPException(
            status_code=422,
            detail="Indicá 'lector_id': el personal no tiene notificaciones propias",
        )
    return lector_id


# ── Notificaciones ────────────────────────────────────────────────────────────

@router.get(
    "/notificaciones",
    response_model=list[NotificacionResponse],
    summary="Avisos de un lector, del más reciente al más viejo",
)
async def listar_notificaciones(
    lector_id: int | None = Query(
        None, description="Sólo para personal: de qué lector. Un lector ve las suyas."
    ),
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    destinatario = await _resolver_destinatario(lector_id, usuario, db)
    result = await db.execute(
        select(Notificacion)
        .where(Notificacion.lector_id == destinatario)
        .order_by(Notificacion.creado_en.desc())
    )
    return result.scalars().all()


@router.post(
    "/notificaciones",
    response_model=NotificacionResponse,
    status_code=201,
    summary="Crear un aviso para un lector",
)
async def crear_notificacion(
    data: NotificacionCreate,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """Las emiten el personal y el ciclo de agentes, nunca el propio lector."""
    lector = await db.get(Lector, data.lector_id)
    if lector is None:
        raise HTTPException(status_code=404, detail="El lector no existe")

    notificacion = Notificacion(
        lector_id=data.lector_id,
        tipo=data.tipo,
        titulo=data.titulo,
        descripcion=data.descripcion,
    )
    db.add(notificacion)
    await db.commit()
    await db.refresh(notificacion)
    return notificacion


@router.patch(
    "/notificaciones/{notificacion_id}/leida",
    response_model=NotificacionResponse,
    summary="Marcar un aviso como leído",
)
async def marcar_leida(
    notificacion_id: int,
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    notificacion = await db.get(Notificacion, notificacion_id)
    if notificacion is None:
        raise HTTPException(status_code=404, detail="La notificación no existe")

    propio = await _lector_id_de(usuario, db)
    if propio is not None and notificacion.lector_id != propio:
        raise HTTPException(status_code=403, detail="Esa notificación no es tuya")

    notificacion.leida = True
    await db.commit()
    await db.refresh(notificacion)
    return notificacion


@router.post(
    "/notificaciones/marcar-leidas",
    summary="Marcar como leídos todos los avisos de un lector",
)
async def marcar_todas_leidas(
    lector_id: int | None = Query(None),
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    destinatario = await _resolver_destinatario(lector_id, usuario, db)
    result = await db.execute(
        select(Notificacion).where(
            Notificacion.lector_id == destinatario,
            Notificacion.leida.is_(False),
        )
    )
    pendientes = result.scalars().all()
    for notificacion in pendientes:
        notificacion.leida = True
    await db.commit()
    return {"marcadas": len(pendientes)}


# ── Auditoría ─────────────────────────────────────────────────────────────────

@router.get(
    "/auditoria",
    response_model=list[EventoAuditoriaResponse],
    summary="Registro de auditoría, del más reciente al más viejo",
)
async def listar_auditoria(
    limite: int = Query(200, ge=1, le=1000),
    tipo: str | None = Query(None, description="Filtrar por tipo de evento"),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    consulta = select(EventoAuditoria).order_by(EventoAuditoria.creado_en.desc())
    if tipo:
        consulta = consulta.where(EventoAuditoria.tipo == tipo)
    result = await db.execute(consulta.limit(limite))
    return result.scalars().all()


@router.post(
    "/auditoria",
    response_model=EventoAuditoriaResponse,
    status_code=201,
    summary="Asentar un evento en el registro de auditoría",
)
async def registrar_auditoria(
    data: EventoAuditoriaCreate,
    usuario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """El autor sale del token y no del cuerpo: quién hizo qué no es un dato
    que el cliente pueda declarar sobre sí mismo."""
    evento = EventoAuditoria(
        tipo=data.tipo,
        descripcion=data.descripcion,
        usuario_id=usuario.id,
    )
    db.add(evento)
    await db.commit()
    await db.refresh(evento)
    return evento


# ── Configuración ─────────────────────────────────────────────────────────────

_CONFIGURACION_POR_DEFECTO = {
    "plazo_prestamo_dias": {
        "infantil": 7,
        "adolescente": 7,
        "adulto": 14,
        "docente": 21,
        "institucional": 30,
    },
    "limite_ejemplares": {
        "infantil": 2,
        "adolescente": 2,
        "adulto": 3,
        "docente": 5,
        "institucional": 5,
    },
    "limite_reservas": {
        "infantil": 2,
        "adolescente": 2,
        "adulto": 3,
        "docente": 5,
        "institucional": 5,
    },
}


async def _configuracion_vigente(db: AsyncSession) -> ConfiguracionBiblioteca:
    """La fila única, creándola con los valores de la spec si todavía no está.

    Se crea acá y no en el arranque para que la primera lectura funcione en una
    base recién migrada sin depender del orden de despliegue.
    """
    config = await db.get(ConfiguracionBiblioteca, ConfiguracionBiblioteca.FILA_UNICA)
    if config is not None:
        return config

    config = ConfiguracionBiblioteca(
        id=ConfiguracionBiblioteca.FILA_UNICA,
        **_CONFIGURACION_POR_DEFECTO,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.get(
    "/configuracion",
    response_model=ConfiguracionResponse,
    summary="Parámetros vigentes de la biblioteca",
)
async def obtener_configuracion(
    _: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """La lee cualquier rol: son los plazos y límites con los que la app
    explica por qué una operación se permite o se niega."""
    return await _configuracion_vigente(db)


@router.put(
    "/configuracion",
    response_model=ConfiguracionResponse,
    summary="Actualizar los parámetros de la biblioteca",
)
async def actualizar_configuracion(
    data: ConfiguracionUpdate,
    usuario: Usuario = Depends(require_administrador),
    db: AsyncSession = Depends(get_db),
):
    config = await _configuracion_vigente(db)
    for campo, valor in data.model_dump().items():
        setattr(config, campo, valor)
    config.actualizado_por_id = usuario.id
    config.actualizado_en = datetime.utcnow()

    # El cambio de parámetros se audita del lado del servidor: es una operación
    # que altera las reglas para todos, y su traza no puede depender de que el
    # cliente se acuerde de asentarla.
    db.add(
        EventoAuditoria(
            tipo="cambio_config",
            descripcion="Se actualizaron los parámetros de la biblioteca",
            usuario_id=usuario.id,
        )
    )
    await db.commit()
    await db.refresh(config)
    return config


# ── Aprendizaje ───────────────────────────────────────────────────────────────

@router.get(
    "/aprendizaje/interacciones",
    response_model=list[InteraccionResponse],
    summary="Interacciones de los lectores con los títulos",
)
async def listar_interacciones(
    limite: int = Query(500, ge=1, le=5000),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InteraccionAprendizaje)
        .order_by(InteraccionAprendizaje.creado_en.desc())
        .limit(limite)
    )
    return result.scalars().all()


@router.post(
    "/aprendizaje/interacciones",
    response_model=InteraccionResponse,
    status_code=201,
    summary="Registrar un clic o una reserva sobre un título",
)
async def registrar_interaccion(
    data: InteraccionCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """Un lector sólo puede registrar interacciones propias: la señal se usa
    agregada, y dejar que declare por otro la ensuciaría."""
    propio = await _lector_id_de(usuario, db)
    if propio is not None and data.lector_id != propio:
        raise HTTPException(
            status_code=403, detail="Sólo podés registrar interacciones propias"
        )

    interaccion = InteraccionAprendizaje(
        lector_id=data.lector_id,
        titulo_id=data.titulo_id,
        tipo=data.tipo,
    )
    db.add(interaccion)
    await db.commit()
    await db.refresh(interaccion)
    return interaccion


@router.get(
    "/aprendizaje/correcciones",
    response_model=list[CorreccionResponse],
    summary="Correcciones del personal sobre las fichas sugeridas",
)
async def listar_correcciones(
    limite: int = Query(500, ge=1, le=5000),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CorreccionAprendizaje)
        .order_by(CorreccionAprendizaje.creado_en.desc())
        .limit(limite)
    )
    return result.scalars().all()


@router.post(
    "/aprendizaje/correcciones",
    response_model=CorreccionResponse,
    status_code=201,
    summary="Registrar una corrección sobre una ficha sugerida",
)
async def registrar_correccion(
    data: CorreccionCreate,
    usuario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    correccion = CorreccionAprendizaje(
        campo=data.campo,
        valor_sugerido=data.valor_sugerido,
        valor_final=data.valor_final,
        usuario_id=usuario.id,
    )
    db.add(correccion)
    await db.commit()
    await db.refresh(correccion)
    return correccion
