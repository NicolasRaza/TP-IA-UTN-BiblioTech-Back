"""
BiblioTech — Interfaces de Repositorio (agentes/repositorios.py)
================================================================
Define las abstracciones (Protocol) que los agentes utilizan para
acceder a datos. El equipo de backend debe implementar estas interfaces
contra la base de datos real.

NO hay dependencias de localStorage, window ni ningún entorno web.
La inyección de dependencias se realiza por constructor en cada agente.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Tipos de datos (estructuras devueltas por los repositorios)
# Representan los mismos shapes de objetos que usaba db.js.
# El backend puede usar dataclasses, TypedDict, Pydantic models, etc.
# ---------------------------------------------------------------------------

# Todos los tipos son dict[str, Any] en la capa de interfaz para máxima
# flexibilidad; el backend decide cómo serializar.  Los keys coinciden
# con los campos del seed de db.js.

Libro       = dict[str, Any]   # {id, titulo, autor, editorial, anio, isbn, sinopsis, genero, paginas, portada, estado, validado, fechaAlta, ejemplares: [...]}
Ejemplar    = dict[str, Any]   # {id, qr, condicion, estado}
Lector      = dict[str, Any]   # {id, nombre, apellido, email, dni, telefono, categoria, tutor, fechaAlta, activo, pin, qr, generosInteres, multasPendientes, [rol]}
Prestamo    = dict[str, Any]   # {id, lectorId, ejemplarId, libroId, fechaPrestamo, fechaVencimiento, fechaDevolucion, estado, tardio}
Reserva     = dict[str, Any]   # {id, lectorId, libroId, fechaReserva, fechaVencimientoRetiro, estado}
Notificacion = dict[str, Any]  # {id, lectorId, tipo, titulo, descripcion, fecha, leida, icono}
ConfigBT    = dict[str, Any]   # {plazoPrestamoDias, limiteEjemplares, limiteReservas, plazoRetiroReservaDias, multaPorDiaDemora, recordatorioAntesDias, motorIaLocal, ollamaEndpoint, ollamaModelo}
DatosAprendizaje = dict[str, Any]  # {correcciones: [...], clics: [...], recomendaciones: [...]}
ElegibilidadResult = dict[str, Any]  # {ok: bool, razon?: str}


# ---------------------------------------------------------------------------
# Protocol: RepositorioLibros
# Equivalente a DB.libros de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioLibros(Protocol):
    async def get_all(self) -> list[Libro]:
        """Devuelve todos los libros (equivalente a DB.libros.getAll())."""
        ...

    async def get(self, libro_id: str) -> Optional[Libro]:
        """Devuelve un libro por ID (equivalente a DB.libros.get(id))."""
        ...

    async def add(self, libro: Libro) -> Libro:
        """Persiste un libro nuevo (equivalente a DB.libros.add(libro))."""
        ...

    async def update(self, libro_id: str, changes: dict[str, Any]) -> Optional[Libro]:
        """Actualiza campos de un libro (equivalente a DB.libros.update(id, changes))."""
        ...

    async def delete(self, libro_id: str) -> None:
        """Elimina un libro (equivalente a DB.libros.delete(id))."""
        ...

    async def add_ejemplar(self, libro_id: str, ejemplar: Ejemplar) -> Optional[Ejemplar]:
        """Agrega un ejemplar a un libro (equivalente a DB.libros.addEjemplar())."""
        ...

    async def get_disponible(self, libro_id: str) -> Optional[Ejemplar]:
        """Devuelve el primer ejemplar disponible (equivalente a DB.libros.getDisponible())."""
        ...

    async def update_ejemplar(self, libro_id: str, ejemplar_id: str, changes: dict[str, Any]) -> None:
        """Actualiza campos de un ejemplar (equivalente a DB.libros.updateEjemplar())."""
        ...

    async def get_by_qr(self, qr: str) -> Optional[dict[str, Any]]:
        """Devuelve {libro, ejemplar} por código QR (equivalente a DB.libros.getByQR())."""
        ...

    async def search(self, q: str = '', genero: str = '') -> list[Libro]:
        """Busca libros validados por texto y/o género (equivalente a DB.libros.search())."""
        ...

    async def get_generos(self) -> list[str]:
        """Devuelve lista de géneros únicos (equivalente a DB.libros.getGeneros())."""
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioLectores
# Equivalente a DB.lectores de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioLectores(Protocol):
    async def get_all(self) -> list[Lector]:
        """Devuelve todos los lectores (sin personal) (equivalente a DB.lectores.getAll())."""
        ...

    async def get(self, lector_id: str) -> Optional[Lector]:
        """Devuelve un lector por ID (equivalente a DB.lectores.get(id))."""
        ...

    async def get_by_email(self, email: str) -> Optional[Lector]:
        """Devuelve un lector por email (equivalente a DB.lectores.getByEmail())."""
        ...

    async def get_by_qr(self, qr: str) -> Optional[Lector]:
        """Devuelve un lector por código QR (equivalente a DB.lectores.getByQR())."""
        ...

    async def add(self, lector: Lector) -> Lector:
        """Persiste un lector nuevo (equivalente a DB.lectores.add())."""
        ...

    async def update(self, lector_id: str, changes: dict[str, Any]) -> Optional[Lector]:
        """Actualiza campos de un lector (equivalente a DB.lectores.update())."""
        ...

    async def can_borrow(self, lector_id: str) -> ElegibilidadResult:
        """
        Evalúa si un lector puede tomar préstamos.
        Equivalente a DB.lectores.canBorrow().
        Devuelve {'ok': bool, 'razon': str|None}.
        Reglas: activo, sin multas, sin vencidos, bajo el límite por categoría.
        """
        ...

    async def can_reserve(self, lector_id: str) -> ElegibilidadResult:
        """
        Evalúa si un lector puede hacer reservas.
        Equivalente a DB.lectores.canReserve().
        Nota: permite reservar aunque tenga préstamos vencidos (BUG FIX del original).
        """
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioPrestamos
# Equivalente a DB.prestamos de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioPrestamos(Protocol):
    async def get_all(self) -> list[Prestamo]:
        """Devuelve todos los préstamos (equivalente a DB.prestamos.getAll())."""
        ...

    async def get(self, prestamo_id: str) -> Optional[Prestamo]:
        """Devuelve un préstamo por ID (equivalente a DB.prestamos.get())."""
        ...

    async def get_by_lector(self, lector_id: str) -> list[Prestamo]:
        """Devuelve préstamos de un lector (equivalente a DB.prestamos.getByLector())."""
        ...

    async def crear(self, lector_id: str, ejemplar_id: str, libro_id: str) -> Prestamo:
        """
        Crea un préstamo, actualiza el ejemplar y cierra la reserva si existe.
        Equivalente a DB.prestamos.crear().
        """
        ...

    async def devolver(self, prestamo_id: str) -> Optional[Prestamo]:
        """
        Registra la devolución, calcula multa si es tardía.
        Equivalente a DB.prestamos.devolver().
        """
        ...

    async def get_stats(self) -> dict[str, Any]:
        """
        Devuelve estadísticas agregadas.
        Equivalente a DB.prestamos.getStats().
        Retorna: {total, activos, vencidos, devueltos, tasa_tardia}
        """
        ...

    async def top_libros(self, n: int = 5) -> list[dict[str, Any]]:
        """
        Devuelve los n libros más prestados.
        Equivalente a DB.prestamos.topLibros().
        Retorna: [{libro: Libro, count: int}]
        """
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioReservas
# Equivalente a DB.reservas de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioReservas(Protocol):
    async def get_all(self) -> list[Reserva]:
        """Devuelve todas las reservas (equivalente a DB.reservas.getAll())."""
        ...

    async def get_by_lector(self, lector_id: str) -> list[Reserva]:
        """Devuelve reservas de un lector (equivalente a DB.reservas.getByLector())."""
        ...

    async def crear(self, lector_id: str, libro_id: str) -> Reserva | dict[str, str]:
        """
        Crea una reserva, validando duplicados y límites.
        Equivalente a DB.reservas.crear().
        Puede devolver {'error': str} si no es posible.
        """
        ...

    async def cancelar(self, reserva_id: str) -> None:
        """Cancela una reserva (equivalente a DB.reservas.cancelar())."""
        ...

    async def marcar_lista(self, reserva_id: str) -> None:
        """
        Marca una reserva como lista para retiro y calcula el vencimiento (48hs).
        Equivalente a DB.reservas.marcarLista().
        """
        ...

    async def get_cola_por_libro(self, libro_id: str) -> list[Reserva]:
        """
        Devuelve la cola de reservas pendientes/listas para un libro.
        Equivalente a DB.reservas.getColaPorLibro().
        """
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioNotificaciones
# Equivalente a DB.notificaciones de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioNotificaciones(Protocol):
    async def get_by_lector(self, lector_id: str) -> list[Notificacion]:
        """
        Devuelve notificaciones de un lector ordenadas por fecha desc.
        Equivalente a DB.notificaciones.getByLector().
        """
        ...

    async def count_unread(self, lector_id: str) -> int:
        """Cuenta notificaciones no leídas (equivalente a DB.notificaciones.countUnread())."""
        ...

    async def add(self, notif: Notificacion) -> None:
        """Agrega una notificación (equivalente a DB.notificaciones.add())."""
        ...

    async def marcar_leida(self, notif_id: str) -> None:
        """Marca una notificación como leída (equivalente a DB.notificaciones.marcarLeida())."""
        ...

    async def marcar_todas_leidas(self, lector_id: str) -> None:
        """Marca todas las notificaciones de un lector como leídas."""
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioConfig
# Equivalente a DB.config de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioConfig(Protocol):
    def get(self) -> ConfigBT:
        """
        Devuelve la configuración del sistema.
        Equivalente a DB.config.get().
        Estructura mínima esperada:
          {
            'plazoPrestamoDias': {'adulto': 14, 'menor': 7, 'docente': 21, 'senior': 14},
            'limiteEjemplares':  {'adulto': 3,  'menor': 2, 'docente': 5,  'senior': 3},
            'limiteReservas':    {'adulto': 3,  'menor': 2, 'docente': 5,  'senior': 3},
            'plazoRetiroReservaDias': 2,
            'multaPorDiaDemora': 100,
            'recordatorioAntesDias': 3,
            'motorIaLocal': 'desactivado',  # 'desactivado' | 'ollama'
            'ollamaEndpoint': 'http://localhost:11434',
            'ollamaModelo': 'gemma4:e2b',
          }
        """
        ...

    def update(self, changes: dict[str, Any]) -> ConfigBT:
        """Actualiza campos de configuración (equivalente a DB.config.update())."""
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioAprendizaje
# Equivalente a DB.aprendizaje de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioAprendizaje(Protocol):
    def get(self) -> DatosAprendizaje:
        """
        Devuelve los datos de aprendizaje.
        Equivalente a DB.aprendizaje.get().
        Estructura: {correcciones: [...], clics: [...], recomendaciones: [...]}
        """
        ...

    def registrar_correccion(self, campo: str, valor_ocr: str, valor_corregido: str) -> None:
        """
        Registra una corrección manual sobre un campo OCR.
        Equivalente a DB.aprendizaje.registrarCorreccion().
        """
        ...

    def registrar_clic(self, lector_id: str, libro_id: str, tipo: str) -> None:
        """
        Registra un clic/acción del lector sobre una recomendación.
        Equivalente a DB.aprendizaje.registrarClic().
        """
        ...


# ---------------------------------------------------------------------------
# Protocol: RepositorioAuditoria
# Equivalente a DB.auditoria de db.js
# ---------------------------------------------------------------------------

@runtime_checkable
class RepositorioAuditoria(Protocol):
    def get_all(self) -> list[dict[str, Any]]:
        """Devuelve todos los registros de auditoría ordenados por fecha desc."""
        ...

    def log(self, tipo: str, descripcion: str, usuario_id: Optional[str] = None) -> None:
        """
        Registra un evento de auditoría.
        Equivalente a DB.auditoria.log().
        """
        ...


# ---------------------------------------------------------------------------
# Clase contenedor opcional: RepositorioBibliotech
# Agrupa todos los repositorios para simplificar la inyección.
# El backend puede instanciar este contenedor o inyectar cada repo por separado.
# ---------------------------------------------------------------------------

class RepositorioBibliotech:
    """
    Contenedor de repositorios BiblioTech.
    Agrupa todos los repositorios para simplificar la construcción de agentes.

    Ejemplo de uso:
        repo = RepositorioBibliotech(
            libros=MiImplLibros(),
            lectores=MiImplLectores(),
            prestamos=MiImplPrestamos(),
            reservas=MiImplReservas(),
            notificaciones=MiImplNotificaciones(),
            config=MiImplConfig(),
            aprendizaje=MiImplAprendizaje(),
            auditoria=MiImplAuditoria(),
        )
        agente = AgenteEvaluador(repo)
    """

    def __init__(
        self,
        libros: RepositorioLibros,
        lectores: RepositorioLectores,
        prestamos: RepositorioPrestamos,
        reservas: RepositorioReservas,
        notificaciones: RepositorioNotificaciones,
        config: RepositorioConfig,
        aprendizaje: RepositorioAprendizaje,
        auditoria: RepositorioAuditoria,
    ) -> None:
        self.libros = libros
        self.lectores = lectores
        self.prestamos = prestamos
        self.reservas = reservas
        self.notificaciones = notificaciones
        self.config = config
        self.aprendizaje = aprendizaje
        self.auditoria = auditoria
