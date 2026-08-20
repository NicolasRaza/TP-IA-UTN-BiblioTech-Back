from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.deps import get_db, get_usuario_actual, require_bibliotecario
from app.core.config import settings
from app.models.usuario import Usuario, Lector, EstadoUsuario, CategoriaLector
from app.models.libro import Ejemplar, EstadoEjemplar, Titulo
from app.models.circulacion import (
    Prestamo, EstadoPrestamo,
    Reserva, EstadoReserva,
    Multa, EstadoMulta, MotivoMulta,
)
from app.schemas.circulacion import (
    PrestamoCreate, DevolucionRequest, PrestamoResponse,
    ReservaCreate, ReservaResponse,
    MultaCreate, MultaUpdate, MultaResponse,
    IndicadoresResponse,
)

router = APIRouter(tags=["Circulación"])


def dias_prestamo_por_categoria(categoria: CategoriaLector) -> int:
    mapa = {
        CategoriaLector.INFANTIL: settings.MAX_DIAS_PRESTAMO_INFANTIL,
        CategoriaLector.ADOLESCENTE: settings.MAX_DIAS_PRESTAMO_ADULTO,
        CategoriaLector.ADULTO: settings.MAX_DIAS_PRESTAMO_ADULTO,
        CategoriaLector.DOCENTE: settings.MAX_DIAS_PRESTAMO_DOCENTE,
        CategoriaLector.INSTITUCIONAL: settings.MAX_DIAS_PRESTAMO_DOCENTE,
    }
    return mapa.get(categoria, settings.MAX_DIAS_PRESTAMO_ADULTO)


async def verificar_lector_habilitado(lector: Lector, db: AsyncSession) -> None:
    """Valida estado, mora y cupo antes de permitir un nuevo préstamo o reserva."""
    if lector.estado == EstadoUsuario.PENDIENTE:
        raise HTTPException(
            status_code=403,
            detail="Lector pendiente de verificación por un bibliotecario",
        )
    if lector.estado == EstadoUsuario.SUSPENDIDO:
        raise HTTPException(
            status_code=403,
            detail="Lector suspendido por mora o multas impagas",
        )
    if lector.estado == EstadoUsuario.BAJA:
        raise HTTPException(status_code=403, detail="Lector dado de baja")

    multas = await db.execute(
        select(func.count()).where(
            Multa.lector_id == lector.id, Multa.estado == EstadoMulta.PENDIENTE
        )
    )
    if multas.scalar() > 0:
        raise HTTPException(status_code=403, detail="Lector con multas impagas")

    prestamos_activos = await db.execute(
        select(func.count()).where(
            Prestamo.lector_id == lector.id, Prestamo.estado == EstadoPrestamo.ACTIVO
        )
    )
    if prestamos_activos.scalar() >= settings.MAX_PRESTAMOS_SIMULTANEOS:
        raise HTTPException(
            status_code=409,
            detail=f"El lector alcanzó el límite de {settings.MAX_PRESTAMOS_SIMULTANEOS} préstamos simultáneos",
        )


# ── Préstamos ─────────────────────────────────────────────────────────────────

@router.post("/prestamos", response_model=PrestamoResponse, status_code=201,
             summary="Registrar préstamo (escanear QR del ejemplar)")
async def crear_prestamo(
    data: PrestamoCreate,
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    El bibliotecario escanea el QR del libro y selecciona el lector.
    El sistema verifica estado del lector, cupo y disponibilidad del ejemplar.
    """
    # Verificar ejemplar
    ej_result = await db.execute(
        select(Ejemplar).where(Ejemplar.codigo_qr == data.qr_ejemplar, Ejemplar.activo == True)
    )
    ejemplar = ej_result.scalar_one_or_none()
    if not ejemplar:
        raise HTTPException(status_code=404, detail="Ejemplar no encontrado o dado de baja")
    if ejemplar.estado != EstadoEjemplar.DISPONIBLE:
        raise HTTPException(status_code=409, detail=f"El ejemplar no está disponible (estado: {ejemplar.estado})")

    # Verificar lector
    lector_result = await db.execute(select(Lector).where(Lector.id == data.lector_id))
    lector = lector_result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Lector no encontrado")

    await verificar_lector_habilitado(lector, db)

    dias = dias_prestamo_por_categoria(lector.categoria)
    hoy = date.today()
    prestamo = Prestamo(
        ejemplar_id=ejemplar.id,
        lector_id=lector.id,
        fecha_inicio=hoy,
        fecha_devolucion_pactada=hoy + timedelta(days=dias),
        estado=EstadoPrestamo.ACTIVO,
        registrado_por_id=bibliotecario.id,
    )
    ejemplar.estado = EstadoEjemplar.PRESTADO

    db.add(prestamo)
    await db.commit()
    await db.refresh(prestamo)

    r = PrestamoResponse.model_validate(prestamo)
    r.titulo_id = ejemplar.titulo_id if ejemplar else None
    r.dias_restantes = (prestamo.fecha_devolucion_pactada - hoy).days
    return r


@router.post("/prestamos/devolucion", response_model=PrestamoResponse,
             summary="Registrar devolución (escanear QR del ejemplar)")
async def registrar_devolucion(
    data: DevolucionRequest,
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Al escanear el QR, el sistema cierra el préstamo activo.
    Si hay reservas pendientes para ese título, notifica automáticamente al primero en la cola.
    """
    ej_result = await db.execute(
        select(Ejemplar).where(Ejemplar.codigo_qr == data.qr_ejemplar)
    )
    ejemplar = ej_result.scalar_one_or_none()
    if not ejemplar:
        raise HTTPException(status_code=404, detail="Ejemplar no encontrado")

    prestamo_result = await db.execute(
        select(Prestamo).where(
            Prestamo.ejemplar_id == ejemplar.id,
            Prestamo.estado == EstadoPrestamo.ACTIVO,
        )
    )
    prestamo = prestamo_result.scalar_one_or_none()
    if not prestamo:
        raise HTTPException(status_code=404, detail="No hay préstamo activo para este ejemplar")

    hoy = date.today()
    prestamo.fecha_devolucion_real = hoy
    prestamo.estado = EstadoPrestamo.DEVUELTO

    # Registrar multa si llegó tarde
    if hoy > prestamo.fecha_devolucion_pactada:
        prestamo.estado = EstadoPrestamo.VENCIDO
        multa = Multa(
            prestamo_id=prestamo.id,
            lector_id=prestamo.lector_id,
            motivo=MotivoMulta.MORA,
        )
        db.add(multa)

    # Verificar reservas pendientes para este título
    reserva_result = await db.execute(
        select(Reserva)
        .where(
            Reserva.titulo_id == ejemplar.titulo_id,
            Reserva.estado == EstadoReserva.EN_COLA,
        )
        .order_by(Reserva.posicion_cola)
        .limit(1)
    )
    reserva_siguiente = reserva_result.scalar_one_or_none()

    if reserva_siguiente:
        reserva_siguiente.estado = EstadoReserva.DISPONIBLE_RETIRO
        reserva_siguiente.fecha_disponible = datetime.utcnow()
        reserva_siguiente.fecha_limite_retiro = datetime.utcnow() + timedelta(
            hours=settings.HORAS_RESERVA_DISPONIBLE
        )
        reserva_siguiente.ejemplar_asignado_id = ejemplar.id
        ejemplar.estado = EstadoEjemplar.RESERVADO
        # Aquí el Agente Planificador dispararía la notificación push
    else:
        ejemplar.estado = EstadoEjemplar.DISPONIBLE

    await db.commit()
    await db.refresh(prestamo)

    r = PrestamoResponse.model_validate(prestamo)
    r.titulo_id = ejemplar.titulo_id if ejemplar else None
    return r


@router.get("/prestamos/lector/{lector_id}", response_model=list[PrestamoResponse],
            summary="Historial de préstamos de un lector")
async def historial_prestamos(
    lector_id: int,
    solo_activos: bool = Query(False),
    _: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    query = select(Prestamo).where(Prestamo.lector_id == lector_id)
    if solo_activos:
        query = query.where(Prestamo.estado == EstadoPrestamo.ACTIVO)

    result = await db.execute(query.order_by(Prestamo.fecha_inicio.desc()))
    prestamos = result.scalars().all()

    hoy = date.today()
    respuestas = []
    for p in prestamos:
        ej = await db.get(Ejemplar, p.ejemplar_id)
        r = PrestamoResponse.model_validate(p)
        r.titulo_id = ej.titulo_id if ej else None
        if p.estado == EstadoPrestamo.ACTIVO:
            r.dias_restantes = (p.fecha_devolucion_pactada - hoy).days
        respuestas.append(r)
    return respuestas


# ── Reservas ──────────────────────────────────────────────────────────────────

@router.post("/reservas", response_model=ReservaResponse, status_code=201,
             summary="Solicitar reserva de un título")
async def crear_reserva(
    data: ReservaCreate,
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """
    El lector reserva desde la app. Se asigna a la cola por orden de llegada.
    No se puede reservar si el lector está suspendido o tiene el cupo lleno.
    """
    lector_result = await db.execute(
        select(Lector).where(Lector.usuario_id == usuario.id)
    )
    lector = lector_result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Perfil de lector no encontrado")

    await verificar_lector_habilitado(lector, db)

    # Verificar que no tenga ya una reserva activa para el mismo título
    ya_reservo = await db.execute(
        select(Reserva).where(
            Reserva.titulo_id == data.titulo_id,
            Reserva.lector_id == lector.id,
            Reserva.estado.in_([EstadoReserva.EN_COLA, EstadoReserva.DISPONIBLE_RETIRO]),
        )
    )
    if ya_reservo.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ya tenés una reserva activa para este título")

    # Calcular posición en la cola
    cola_result = await db.execute(
        select(func.count()).where(
            Reserva.titulo_id == data.titulo_id,
            Reserva.estado == EstadoReserva.EN_COLA,
        )
    )
    posicion = cola_result.scalar() + 1

    reserva = Reserva(
        titulo_id=data.titulo_id,
        lector_id=lector.id,
        posicion_cola=posicion,
    )
    db.add(reserva)
    await db.commit()
    await db.refresh(reserva)
    return reserva


@router.delete("/reservas/{reserva_id}", summary="Cancelar reserva")
async def cancelar_reserva(
    reserva_id: int,
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Reserva).where(Reserva.id == reserva_id))
    reserva = result.scalar_one_or_none()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    lector_result = await db.execute(
        select(Lector).where(Lector.usuario_id == usuario.id)
    )
    lector = lector_result.scalar_one_or_none()

    # Solo el propio lector o un bibliotecario pueden cancelar
    if not lector or (reserva.lector_id != lector.id and usuario.rol not in ("bibliotecario", "administrador")):
        raise HTTPException(status_code=403, detail="Sin permiso para cancelar esta reserva")

    reserva.estado = EstadoReserva.CANCELADA
    await db.commit()
    return {"mensaje": "Reserva cancelada"}


@router.get("/reservas/lector/{lector_id}", response_model=list[ReservaResponse],
            summary="Reservas activas de un lector")
async def reservas_lector(
    lector_id: int,
    _: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Reserva)
        .where(
            Reserva.lector_id == lector_id,
            Reserva.estado.in_([EstadoReserva.EN_COLA, EstadoReserva.DISPONIBLE_RETIRO]),
        )
        .order_by(Reserva.fecha_solicitud)
    )
    return result.scalars().all()


# ── Multas ────────────────────────────────────────────────────────────────────

@router.get("/multas/lector/{lector_id}", response_model=list[MultaResponse],
            summary="Multas de un lector")
async def multas_lector(
    lector_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Multa).where(Multa.lector_id == lector_id).order_by(Multa.creado_en.desc())
    )
    return result.scalars().all()


@router.patch("/multas/{multa_id}", response_model=MultaResponse,
              summary="Actualizar estado de multa (pagar o condonar)")
async def actualizar_multa(
    multa_id: int,
    data: MultaUpdate,
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Multa).where(Multa.id == multa_id))
    multa = result.scalar_one_or_none()
    if not multa:
        raise HTTPException(status_code=404, detail="Multa no encontrada")

    multa.estado = data.estado
    if data.observaciones:
        multa.observaciones = data.observaciones

    # Si no quedan multas pendientes, reactivar al lector
    pendientes = await db.execute(
        select(func.count()).where(
            Multa.lector_id == multa.lector_id,
            Multa.estado == EstadoMulta.PENDIENTE,
            Multa.id != multa_id,
        )
    )
    if pendientes.scalar() == 0:
        lector_result = await db.execute(select(Lector).where(Lector.id == multa.lector_id))
        lector = lector_result.scalar_one_or_none()
        if lector and lector.estado == EstadoUsuario.SUSPENDIDO:
            lector.estado = EstadoUsuario.ACTIVO

    await db.commit()
    await db.refresh(multa)
    return multa


# ── Dashboard / Indicadores ───────────────────────────────────────────────────

@router.get("/dashboard/indicadores", response_model=IndicadoresResponse,
            summary="Indicadores operativos para el bibliotecario")
async def indicadores(
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    total_lectores = await db.execute(
        select(func.count()).where(Lector.estado == EstadoUsuario.ACTIVO)
    )
    prestamos_activos = await db.execute(
        select(func.count()).where(Prestamo.estado == EstadoPrestamo.ACTIVO)
    )
    prestamos_vencidos = await db.execute(
        select(func.count()).where(
            Prestamo.estado == EstadoPrestamo.ACTIVO,
            Prestamo.fecha_devolucion_pactada < date.today(),
        )
    )
    reservas_cola = await db.execute(
        select(func.count()).where(Reserva.estado == EstadoReserva.EN_COLA)
    )
    total_devueltos = await db.execute(
        select(func.count()).where(Prestamo.estado.in_([EstadoPrestamo.DEVUELTO, EstadoPrestamo.VENCIDO]))
    )
    devueltos_tiempo = await db.execute(
        select(func.count()).where(Prestamo.estado == EstadoPrestamo.DEVUELTO)
    )

    total_d = total_devueltos.scalar() or 1
    tasa = round(devueltos_tiempo.scalar() / total_d * 100, 1)

    # Top 5 títulos más prestados
    top_titulos_result = await db.execute(
        select(Titulo.titulo, func.count(Prestamo.id).label("total"))
        .join(Ejemplar, Ejemplar.titulo_id == Titulo.id)
        .join(Prestamo, Prestamo.ejemplar_id == Ejemplar.id)
        .group_by(Titulo.id)
        .order_by(func.count(Prestamo.id).desc())
        .limit(5)
    )
    top_titulos = [{"titulo": r[0], "prestamos": r[1]} for r in top_titulos_result]

    # Top 5 lectores más activos
    top_lectores_result = await db.execute(
        select(
            Lector.nombre, Lector.apellido, func.count(Prestamo.id).label("total")
        )
        .join(Prestamo, Prestamo.lector_id == Lector.id)
        .group_by(Lector.id)
        .order_by(func.count(Prestamo.id).desc())
        .limit(5)
    )
    top_lectores = [
        {"lector": f"{r[0]} {r[1]}", "prestamos": r[2]} for r in top_lectores_result
    ]

    return IndicadoresResponse(
        total_lectores_activos=total_lectores.scalar(),
        total_prestamos_activos=prestamos_activos.scalar(),
        total_prestamos_vencidos=prestamos_vencidos.scalar(),
        total_reservas_en_cola=reservas_cola.scalar(),
        tasa_devolucion_tiempo=tasa,
        top_titulos_prestados=top_titulos,
        top_lectores_activos=top_lectores,
    )


# ── Recomendaciones (AgenteAprendizaje) ───────────────────────────────────

@router.get("/recomendaciones", summary="Recomendaciones personalizadas para el lector autenticado")
async def recomendaciones(
    usuario: Usuario = Depends(get_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """
    Usa el AgenteAprendizaje para generar recomendaciones personalizadas.
    Cold start (≤5 préstamos): 100% popularidad.
    Normal: 70% historial + 30% popularidad.
    """
    from app.agents.agente_aprendizaje import AgenteAprendizaje
    from app.agents.repositorios_impl import construir_repositorio

    lector_result = await db.execute(select(Lector).where(Lector.usuario_id == usuario.id))
    lector = lector_result.scalar_one_or_none()
    if not lector:
        raise HTTPException(status_code=404, detail="Perfil de lector no encontrado")

    repo = construir_repositorio(db)
    agente = AgenteAprendizaje(repo)
    libros = await agente.recomendar_para_lector(str(lector.id))
    return libros


@router.get("/dashboard/resumen-ia", summary="Resumen ejecutivo generado por AgenteEvaluador")
async def resumen_ia(
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """Genera un resumen en lenguaje natural con los indicadores de uso (Ollama opcional)."""
    from app.agents.agente_evaluador import AgenteEvaluador
    from app.agents.repositorios_impl import construir_repositorio

    repo = construir_repositorio(db)
    evaluador = AgenteEvaluador(repo)
    indicadores = await evaluador.calcular_indicadores()
    resumen = await evaluador.generar_resumen_con_ia(indicadores)
    return {"indicadores": indicadores, "resumen": resumen}


@router.get("/dashboard/alertas-operativas", summary="Alertas operativas generadas por AgentePlanificador")
async def alertas_operativas(
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Ejecuta el ciclo de orquestación operativa del AgentePlanificador:
    - Evalúa y procesa reservas expiradas (> 48hs).
    - Detecta préstamos vencidos y próximos a vencer.
    - Genera notificaciones proactivas y devuelve el resumen consolidado de alertas.
    """
    from app.agents.agente_evaluador import AgenteEvaluador
    from app.agents.agente_planificador import AgentePlanificador
    from app.agents.repositorios_impl import construir_repositorio

    repo = construir_repositorio(db)
    evaluador = AgenteEvaluador(repo)
    planificador = AgentePlanificador(repo, evaluador)
    return await planificador.resumen_alertas()


@router.get(
    "/prestamos",
    response_model=list[PrestamoResponse],
    summary="Listar todos los préstamos",
    description="""
Retorna todos los préstamos del sistema. Filtrá por estado con el parámetro `estado`.

Incluye `titulo_id` en cada préstamo para resolver el libro sin requests adicionales.

**Estados posibles:** `activo`, `devuelto`, `vencido`

Solo accesible para bibliotecarios y administradores.
    """,
    tags=["Circulación"],
)
async def listar_prestamos(
    estado: EstadoPrestamo | None = Query(None),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    query = select(Prestamo)
    if estado:
        query = query.where(Prestamo.estado == estado)
    result = await db.execute(query.order_by(Prestamo.fecha_inicio.desc()))
    prestamos = result.scalars().all()

    hoy = date.today()
    respuestas = []
    for p in prestamos:
        ej = await db.get(Ejemplar, p.ejemplar_id)
        r = PrestamoResponse.model_validate(p)
        r.titulo_id = ej.titulo_id if ej else None
        if p.estado == EstadoPrestamo.ACTIVO:
            r.dias_restantes = (p.fecha_devolucion_pactada - hoy).days
        respuestas.append(r)
    return respuestas


@router.get(
    "/reservas",
    response_model=list[ReservaResponse],
    summary="Listar todas las reservas",
    description="Retorna todas las reservas del sistema. Filtrá por estado con el parámetro `estado`.",
    tags=["Circulación"],
)
async def listar_reservas(
    estado: EstadoReserva | None = Query(None),
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    query = select(Reserva)
    if estado:
        query = query.where(Reserva.estado == estado)
    result = await db.execute(query.order_by(Reserva.fecha_solicitud.desc()))
    return result.scalars().all()