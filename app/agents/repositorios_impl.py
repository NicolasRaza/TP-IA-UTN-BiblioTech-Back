"""
BiblioTech — Implementaciones concretas de los Protocols de repositorio.

Conecta los agentes del compañero con nuestra base de datos PostgreSQL
via SQLAlchemy. Cada clase implementa el Protocol correspondiente definido
en repositorios.py y traduce entre el modelo de los agentes (camelCase, JS)
y los modelos SQLAlchemy del backend (snake_case, Python).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usuario import Lector, EstadoUsuario, CategoriaLector
from app.models.libro import Titulo, Ejemplar, EstadoEjemplar, EstadoValidacion
from app.models.circulacion import Prestamo, EstadoPrestamo, Reserva, EstadoReserva, Multa, EstadoMulta
from app.models.usuario import Usuario
from app.core.config import settings


# ── Helpers de traducción ──────────────────────────────────────────────────

def _titulo_to_libro(titulo: Titulo, ejemplares: list[Ejemplar] = []) -> dict:
    """Convierte un modelo Titulo + Ejemplares al shape que esperan los agentes."""
    return {
        "id": str(titulo.id),
        "titulo": titulo.titulo,
        "autor": titulo.autores,
        "editorial": titulo.editorial or "",
        "anio": titulo.anio_edicion or "",
        "isbn": titulo.isbn or "",
        "sinopsis": titulo.sinopsis or "",
        "genero": titulo.genero or "",
        "paginas": str(titulo.paginas) if titulo.paginas else "",
        "portada": titulo.portada_url or "",
        "validado": titulo.estado_validacion == EstadoValidacion.VALIDADO,
        "fechaAlta": titulo.creado_en.isoformat(),
        "ejemplares": [
            {
                "id": str(e.id),
                "qr": e.codigo_qr,
                "condicion": e.condicion.value,
                "estado": e.estado.value,
            }
            for e in ejemplares
        ],
    }


def _lector_to_dict(lector: Lector) -> dict:
    """Convierte un modelo Lector al shape que esperan los agentes."""
    return {
        "id": str(lector.id),
        "nombre": lector.nombre,
        "apellido": lector.apellido,
        "email": lector.usuario.email if lector.usuario else "",
        "dni": lector.documento,
        "telefono": lector.telefono or "",
        "categoria": lector.categoria.value,
        "tutor": lector.tutor_nombre or "",
        "fechaAlta": lector.fecha_alta.isoformat(),
        "activo": lector.estado == EstadoUsuario.ACTIVO,
        "qr": f"LEC-{lector.id}",
        "generosInteres": [],
        "multasPendientes": 0,  # se rellena on-demand
    }


def _prestamo_to_dict(prestamo: Prestamo) -> dict:
    """Convierte un modelo Prestamo al shape que esperan los agentes."""
    return {
        "id": str(prestamo.id),
        "lectorId": str(prestamo.lector_id),
        "ejemplarId": str(prestamo.ejemplar_id),
        "libroId": str(prestamo.ejemplar.titulo_id) if prestamo.ejemplar else "",
        "fechaPrestamo": prestamo.fecha_inicio.isoformat(),
        "fechaVencimiento": datetime.combine(
            prestamo.fecha_devolucion_pactada, datetime.min.time()
        ).replace(tzinfo=timezone.utc).isoformat(),
        "fechaDevolucion": prestamo.fecha_devolucion_real.isoformat() if prestamo.fecha_devolucion_real else None,
        "estado": prestamo.estado.value,
        "tardio": (
            prestamo.fecha_devolucion_real > prestamo.fecha_devolucion_pactada
            if prestamo.fecha_devolucion_real else False
        ),
    }


def _reserva_to_dict(reserva: Reserva) -> dict:
    """Convierte un modelo Reserva al shape que esperan los agentes."""
    return {
        "id": str(reserva.id),
        "lectorId": str(reserva.lector_id),
        "libroId": str(reserva.titulo_id),
        "fechaReserva": reserva.fecha_solicitud.isoformat(),
        "fechaVencimientoRetiro": reserva.fecha_limite_retiro.isoformat() if reserva.fecha_limite_retiro else None,
        "estado": "lista" if reserva.estado == EstadoReserva.DISPONIBLE_RETIRO else reserva.estado.value,
    }


# ── Implementaciones concretas ─────────────────────────────────────────────

class RepoLibros:
    """Implementación de RepositorioLibros contra PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_all(self) -> list[dict]:
        result = await self._db.execute(
            select(Titulo).where(Titulo.estado_validacion == EstadoValidacion.VALIDADO)
        )
        titulos = result.scalars().all()
        out = []
        for t in titulos:
            ejs_r = await self._db.execute(select(Ejemplar).where(Ejemplar.titulo_id == t.id, Ejemplar.activo == True))
            out.append(_titulo_to_libro(t, ejs_r.scalars().all()))
        return out

    async def get(self, libro_id: str) -> Optional[dict]:
        result = await self._db.execute(select(Titulo).where(Titulo.id == int(libro_id)))
        titulo = result.scalar_one_or_none()
        if not titulo:
            return None
        ejs_r = await self._db.execute(select(Ejemplar).where(Ejemplar.titulo_id == titulo.id, Ejemplar.activo == True))
        return _titulo_to_libro(titulo, ejs_r.scalars().all())

    async def search(self, q: str = "", genero: str = "") -> list[dict]:
        query = select(Titulo).where(Titulo.estado_validacion == EstadoValidacion.VALIDADO)
        if q:
            query = query.where(
                Titulo.titulo.ilike(f"%{q}%") |
                Titulo.autores.ilike(f"%{q}%") |
                Titulo.isbn.ilike(f"%{q}%")
            )
        if genero:
            query = query.where(Titulo.genero.ilike(f"%{genero}%"))
        result = await self._db.execute(query)
        titulos = result.scalars().all()
        out = []
        for t in titulos:
            ejs_r = await self._db.execute(select(Ejemplar).where(Ejemplar.titulo_id == t.id, Ejemplar.activo == True))
            out.append(_titulo_to_libro(t, ejs_r.scalars().all()))
        return out

    async def get_disponible(self, libro_id: str) -> Optional[dict]:
        result = await self._db.execute(
            select(Ejemplar).where(
                Ejemplar.titulo_id == int(libro_id),
                Ejemplar.estado == EstadoEjemplar.DISPONIBLE,
                Ejemplar.activo == True,
            ).limit(1)
        )
        ej = result.scalar_one_or_none()
        if not ej:
            return None
        return {"id": str(ej.id), "qr": ej.codigo_qr, "condicion": ej.condicion.value, "estado": ej.estado.value}

    async def get_by_qr(self, qr: str) -> Optional[dict]:
        result = await self._db.execute(select(Ejemplar).where(Ejemplar.codigo_qr == qr))
        ej = result.scalar_one_or_none()
        if not ej:
            return None
        titulo = await self._db.get(Titulo, ej.titulo_id)
        return {
            "libro": _titulo_to_libro(titulo, [ej]),
            "ejemplar": {"id": str(ej.id), "qr": ej.codigo_qr, "condicion": ej.condicion.value, "estado": ej.estado.value},
        }

    async def get_generos(self) -> list[str]:
        result = await self._db.execute(
            select(Titulo.genero).where(
                Titulo.genero.isnot(None),
                Titulo.estado_validacion == EstadoValidacion.VALIDADO
            ).distinct()
        )
        return [r[0] for r in result.all() if r[0]]


class RepoLectores:
    """Implementación de RepositorioLectores contra PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_all(self) -> list[dict]:
        result = await self._db.execute(
            select(Lector).where(Lector.estado != EstadoUsuario.BAJA)
        )
        return [_lector_to_dict(l) for l in result.scalars().all()]

    async def get(self, lector_id: str) -> Optional[dict]:
        result = await self._db.execute(select(Lector).where(Lector.id == int(lector_id)))
        lector = result.scalar_one_or_none()
        if not lector:
            return None
        d = _lector_to_dict(lector)
        # Contar multas pendientes
        multas_r = await self._db.execute(
            select(func.count()).where(Multa.lector_id == lector.id, Multa.estado == EstadoMulta.PENDIENTE)
        )
        d["multasPendientes"] = multas_r.scalar()
        return d

    async def get_by_email(self, email: str) -> Optional[dict]:
        result = await self._db.execute(
            select(Lector).join(Usuario).where(Usuario.email == email)
        )
        lector = result.scalar_one_or_none()
        return _lector_to_dict(lector) if lector else None

    async def get_by_qr(self, qr: str) -> Optional[dict]:
        # QR de lector tiene formato LEC-{id}
        if not qr.upper().startswith("LEC-"):
            return None
        lector_id = qr[4:]
        return await self.get(lector_id)

    async def can_borrow(self, lector_id: str) -> dict:
        lector_r = await self._db.execute(select(Lector).where(Lector.id == int(lector_id)))
        lector = lector_r.scalar_one_or_none()
        if not lector or lector.estado != EstadoUsuario.ACTIVO:
            return {"ok": False, "razon": "Lector inactivo o no encontrado"}

        multas_r = await self._db.execute(
            select(func.count()).where(Multa.lector_id == lector.id, Multa.estado == EstadoMulta.PENDIENTE)
        )
        if multas_r.scalar() > 0:
            return {"ok": False, "razon": "Tiene multas pendientes"}

        prestamos_r = await self._db.execute(
            select(func.count()).where(
                Prestamo.lector_id == lector.id,
                Prestamo.estado == EstadoPrestamo.ACTIVO,
            )
        )
        if prestamos_r.scalar() >= settings.MAX_PRESTAMOS_SIMULTANEOS:
            return {"ok": False, "razon": f"Límite de {settings.MAX_PRESTAMOS_SIMULTANEOS} préstamos simultáneos alcanzado"}

        return {"ok": True}

    async def can_reserve(self, lector_id: str) -> dict:
        lector_r = await self._db.execute(select(Lector).where(Lector.id == int(lector_id)))
        lector = lector_r.scalar_one_or_none()
        if not lector or lector.estado != EstadoUsuario.ACTIVO:
            return {"ok": False, "razon": "Lector inactivo o no encontrado"}
        return {"ok": True}


class RepoPrestamos:
    """Implementación de RepositorioPrestamos contra PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_all(self) -> list[dict]:
        result = await self._db.execute(select(Prestamo))
        return [_prestamo_to_dict(p) for p in result.scalars().all()]

    async def get(self, prestamo_id: str) -> Optional[dict]:
        result = await self._db.execute(select(Prestamo).where(Prestamo.id == int(prestamo_id)))
        p = result.scalar_one_or_none()
        return _prestamo_to_dict(p) if p else None

    async def get_by_lector(self, lector_id: str) -> list[dict]:
        result = await self._db.execute(
            select(Prestamo).where(Prestamo.lector_id == int(lector_id))
        )
        return [_prestamo_to_dict(p) for p in result.scalars().all()]

    async def get_stats(self) -> dict:
        total_r = await self._db.execute(select(func.count(Prestamo.id)))
        activos_r = await self._db.execute(
            select(func.count()).where(Prestamo.estado == EstadoPrestamo.ACTIVO)
        )
        vencidos_r = await self._db.execute(
            select(func.count()).where(
                Prestamo.estado == EstadoPrestamo.ACTIVO,
                Prestamo.fecha_devolucion_pactada < datetime.utcnow().date()
            )
        )
        devueltos_r = await self._db.execute(
            select(func.count()).where(Prestamo.estado == EstadoPrestamo.DEVUELTO)
        )
        return {
            "total": total_r.scalar(),
            "activos": activos_r.scalar(),
            "vencidos": vencidos_r.scalar(),
            "devueltos": devueltos_r.scalar(),
        }


class RepoReservas:
    """Implementación de RepositorioReservas contra PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_all(self) -> list[dict]:
        result = await self._db.execute(select(Reserva))
        return [_reserva_to_dict(r) for r in result.scalars().all()]

    async def get_by_lector(self, lector_id: str) -> list[dict]:
        result = await self._db.execute(
            select(Reserva).where(
                Reserva.lector_id == int(lector_id),
                Reserva.estado.in_([EstadoReserva.EN_COLA, EstadoReserva.DISPONIBLE_RETIRO])
            )
        )
        return [_reserva_to_dict(r) for r in result.scalars().all()]

    async def cancelar(self, reserva_id: str) -> None:
        result = await self._db.execute(select(Reserva).where(Reserva.id == int(reserva_id)))
        reserva = result.scalar_one_or_none()
        if reserva:
            reserva.estado = EstadoReserva.VENCIDA
            await self._db.commit()

    async def marcar_lista(self, reserva_id: str) -> None:
        result = await self._db.execute(select(Reserva).where(Reserva.id == int(reserva_id)))
        reserva = result.scalar_one_or_none()
        if reserva:
            reserva.estado = EstadoReserva.DISPONIBLE_RETIRO
            reserva.fecha_disponible = datetime.utcnow()
            reserva.fecha_limite_retiro = datetime.utcnow() + timedelta(hours=settings.HORAS_RESERVA_DISPONIBLE)
            await self._db.commit()

    async def get_cola_por_libro(self, libro_id: str) -> list[dict]:
        result = await self._db.execute(
            select(Reserva).where(
                Reserva.titulo_id == int(libro_id),
                Reserva.estado.in_([EstadoReserva.EN_COLA, EstadoReserva.DISPONIBLE_RETIRO])
            ).order_by(Reserva.posicion_cola)
        )
        return [_reserva_to_dict(r) for r in result.scalars().all()]


class RepoNotificaciones:
    """Implementación de RepositorioNotificaciones contra PostgreSQL."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_lector(self, lector_id: str) -> list[dict]:
        from app.models.circulacion import Notificacion as NotifModel
        result = await self._db.execute(
            select(NotifModel).where(NotifModel.id_lector == int(lector_id))
            .order_by(NotifModel.fecha_envio.desc())
        )
        return [
            {
                "id": str(n.id),
                "lectorId": str(n.id_lector),
                "tipo": n.tipo.value,
                "titulo": n.tipo.value,
                "descripcion": "",
                "fecha": n.fecha_envio.isoformat(),
                "leida": n.estado.value == "leida",
            }
            for n in result.scalars().all()
        ]

    async def count_unread(self, lector_id: str) -> int:
        from app.models.circulacion import Notificacion as NotifModel, EstadoNotif
        result = await self._db.execute(
            select(func.count()).where(
                NotifModel.id_lector == int(lector_id),
                NotifModel.estado == EstadoNotif.ENVIADA,
            )
        )
        return result.scalar()

    async def add(self, notif: dict) -> None:
        # Las notificaciones push se envían via Firebase en planner_old.py
        # Aquí solo logueamos para no perder el evento
        import logging
        logging.getLogger(__name__).info(
            "[RepoNotificaciones] Notificación para lector %s: %s — %s",
            notif.get("lectorId"), notif.get("titulo"), notif.get("descripcion")
        )


class RepoConfig:
    """Implementación de RepositorioConfig leyendo desde settings."""

    def get(self) -> dict:
        return {
            "plazoPrestamoDias": {
                "adulto":  settings.MAX_DIAS_PRESTAMO_ADULTO,
                "menor":   settings.MAX_DIAS_PRESTAMO_INFANTIL,
                "docente": settings.MAX_DIAS_PRESTAMO_DOCENTE,
                "senior":  settings.MAX_DIAS_PRESTAMO_ADULTO,
            },
            "limiteSimultaneo":       settings.MAX_PRESTAMOS_SIMULTANEOS,
            "plazoRetiroReservaDias": settings.HORAS_RESERVA_DISPONIBLE // 24,
            "recordatorioAntesDias":  3,
            "motorIaLocal":           "desactivado",  # cambiar a "ollama" si se configura
            "ollamaEndpoint":         "http://localhost:11434",
            "ollamaModelo":           "gemma4:e2b",
        }

    def update(self, changes: dict) -> dict:
        # En esta versión la config es de solo lectura desde .env
        return self.get()


class RepoAprendizaje:
    """Implementación mínima de RepositorioAprendizaje (persiste en memoria por ahora)."""

    _store: dict = {"correcciones": [], "clics": [], "recomendaciones": []}

    def get(self) -> dict:
        return self._store

    def registrar_correccion(self, campo: str, valor_ocr: str, valor_corregido: str) -> None:
        self._store["correcciones"].append({
            "campo": campo,
            "valorOcr": valor_ocr,
            "valorCorregido": valor_corregido,
            "fecha": datetime.utcnow().isoformat(),
        })

    def registrar_clic(self, lector_id: str, libro_id: str, tipo: str) -> None:
        self._store["clics"].append({
            "lectorId": lector_id,
            "libroId": libro_id,
            "tipo": tipo,
            "fecha": datetime.utcnow().isoformat(),
        })


class RepoAuditoria:
    """Implementación de RepositorioAuditoria (log en consola por ahora)."""

    _registros: list = []

    def get_all(self) -> list:
        return list(reversed(self._registros))

    def log(self, tipo: str, descripcion: str, usuario_id: Optional[str] = None) -> None:
        import logging
        logging.getLogger(__name__).info("[AUDITORIA] %s | %s | user=%s", tipo, descripcion, usuario_id)
        self._registros.append({
            "tipo": tipo,
            "descripcion": descripcion,
            "usuarioId": usuario_id,
            "fecha": datetime.utcnow().isoformat(),
        })


# ── Factory: construir el RepositorioBibliotech completo ──────────────────

def construir_repositorio(db: AsyncSession):
    """
    Construye el contenedor RepositorioBibliotech con todas las implementaciones
    concretas listas para ser inyectadas en los agentes.

    Uso en un endpoint FastAPI:
        repo = construir_repositorio(db)
        evaluador = AgenteEvaluador(repo)
        planificador = AgentePlanificador(repo, evaluador)
    """
    from app.agents.repositorios import RepositorioBibliotech
    return RepositorioBibliotech(
        libros=RepoLibros(db),
        lectores=RepoLectores(db),
        prestamos=RepoPrestamos(db),
        reservas=RepoReservas(db),
        notificaciones=RepoNotificaciones(db),
        config=RepoConfig(),
        aprendizaje=RepoAprendizaje(),
        auditoria=RepoAuditoria(),
    )
