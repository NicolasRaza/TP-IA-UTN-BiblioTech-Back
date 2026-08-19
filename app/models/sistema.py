"""Tablas de las features transversales del sistema.

Notificaciones, auditoría, parámetros de la biblioteca y memoria del Agente de
Aprendizaje. Las cuatro tienen algo en común: no son parte de ninguno de los
tres pilares (lectores, catálogo, circulación) pero los atraviesan a todos, y
hasta ahora vivían en el almacenamiento del navegador de cada cliente. Eso
significaba que la traza de auditoría se perdía al limpiar el cache, que dos
bibliotecarios veían parámetros distintos y que las notificaciones de un
lector no lo seguían de un dispositivo a otro.
"""

import enum
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class TipoNotificacion(str, enum.Enum):
    VENCIMIENTO_PROXIMO = "vencimiento_proximo"
    PRESTAMO_VENCIDO = "prestamo_vencido"
    RESERVA_DISPONIBLE = "reserva_disponible"
    RESERVA_CONFIRMADA = "reserva_confirmada"
    RESERVA_VENCIDA = "reserva_vencida"
    RECOMENDACION = "recomendacion"


class Notificacion(Base):
    """Aviso dirigido a un lector.

    Las genera el Agente Planificador al ejecutar sus decisiones y los flujos
    de préstamo y reserva. Se leen y se marcan como leídas desde el portal del
    lector.
    """

    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lectores.id"), index=True, nullable=False
    )
    tipo: Mapped[TipoNotificacion] = mapped_column(Enum(TipoNotificacion), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    leida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EventoAuditoria(Base):
    """Entrada del registro de auditoría. Append-only: nunca se edita ni se borra.

    `tipo` es texto y no un Enum a propósito. El vocabulario de eventos crece
    cada vez que se audita una operación nueva, y sobre Postgres agregarle un
    valor a un tipo enumerado es una migración; acá un evento nuevo es
    simplemente una fila nueva. La lista vigente está en `TIPOS_CONOCIDOS`, que
    documenta sin bloquear.
    """

    __tablename__ = "eventos_auditoria"

    TIPOS_CONOCIDOS = (
        "alta_libro",
        "baja_libro",
        "edicion_libro",
        "alta_lector",
        "edicion_lector",
        "verificacion_lector",
        "alta_usuario_interno",
        "baja_usuario_interno",
        "prestamo",
        "devolucion",
        "reimpresion_qr",
        "correccion_ocr",
        "cambio_categoria",
        "cambio_config",
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("usuarios.id"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class ConfiguracionBiblioteca(Base):
    """Parámetros que el administrador edita (spec v2 §3).

    Es una tabla de una sola fila, fijada en `id = 1` por [FILA_UNICA]: los
    plazos y límites son del sistema, no de cada instalación. Guardarlos acá y
    no en el cliente es lo que hace que un cambio de plazo valga para todos y
    no sólo para el navegador donde se tocó.

    Los tres límites por categoría van en columnas JSON porque son mapas
    `categoria -> número` y el conjunto de categorías es del dominio, no de la
    base: agregar una categoría no debería ser una migración de esquema.
    """

    __tablename__ = "configuracion_biblioteca"

    FILA_UNICA = 1

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=FILA_UNICA)
    plazo_prestamo_dias: Mapped[dict] = mapped_column(JSON, nullable=False)
    limite_ejemplares: Mapped[dict] = mapped_column(JSON, nullable=False)
    limite_reservas: Mapped[dict] = mapped_column(JSON, nullable=False)
    plazo_retiro_reserva_horas: Mapped[int] = mapped_column(Integer, default=48)
    multa_por_dia_demora: Mapped[int] = mapped_column(Integer, default=100)
    recordatorio_antes_dias: Mapped[int] = mapped_column(Integer, default=3)
    peso_historial_recomendacion: Mapped[float] = mapped_column(Float, default=0.7)
    min_prestamos_para_historial: Mapped[int] = mapped_column(Integer, default=5)
    edad_mayoria_edad: Mapped[int] = mapped_column(Integer, default=18)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    actualizado_por_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("usuarios.id"), nullable=True
    )


class InteraccionAprendizaje(Base):
    """Clic o reserva de un lector sobre un título.

    Insumo del ciclo de retroalimentación de la spec v2 §5: con esto el Agente
    de Aprendizaje mide qué recomendaciones se aceptan. Tiene que ser del
    servidor porque la señal sirve agregada sobre todos los lectores, y en el
    cliente cada uno veía sólo la suya.
    """

    __tablename__ = "interacciones_aprendizaje"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lectores.id"), index=True, nullable=False
    )
    titulo_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("titulos.id"), index=True, nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CorreccionAprendizaje(Base):
    """Corrección de un bibliotecario sobre una ficha sugerida por el OCR.

    Cada fila es "el agente propuso esto y la persona lo dejó así": el material
    con el que el Agente de Aprendizaje ajusta sus sugerencias.
    """

    __tablename__ = "correcciones_aprendizaje"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    campo: Mapped[str] = mapped_column(String(50), nullable=False)
    valor_sugerido: Mapped[str] = mapped_column(Text, nullable=False)
    valor_final: Mapped[str] = mapped_column(Text, nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("usuarios.id"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
