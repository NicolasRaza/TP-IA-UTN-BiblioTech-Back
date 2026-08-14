import enum
from datetime import date, datetime
from sqlalchemy import String, Enum, Date, DateTime, Integer, Numeric, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class EstadoPrestamo(str, enum.Enum):
    ACTIVO = "activo"
    DEVUELTO = "devuelto"
    VENCIDO = "vencido"


class EstadoReserva(str, enum.Enum):
    EN_COLA = "en_cola"
    DISPONIBLE_RETIRO = "disponible_para_retiro"
    RETIRADA = "retirada"
    CANCELADA = "cancelada"
    VENCIDA = "vencida"


class MotivoMulta(str, enum.Enum):
    MORA = "mora"
    DANIO = "danio"
    PERDIDA = "perdida"


class EstadoMulta(str, enum.Enum):
    PENDIENTE = "pendiente"
    PAGADA = "pagada"
    CONDONADA = "condonada"


class Prestamo(Base):
    __tablename__ = "prestamos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ejemplar_id: Mapped[int] = mapped_column(Integer, ForeignKey("ejemplares.id"), nullable=False)
    lector_id: Mapped[int] = mapped_column(Integer, ForeignKey("lectores.id"), nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_devolucion_pactada: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_devolucion_real: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[EstadoPrestamo] = mapped_column(Enum(EstadoPrestamo), default=EstadoPrestamo.ACTIVO)
    registrado_por_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ejemplar: Mapped["Ejemplar"] = relationship("Ejemplar", back_populates="prestamos")  # noqa: F821
    lector: Mapped["Lector"] = relationship("Lector", back_populates="prestamos")  # noqa: F821
    multa: Mapped["Multa | None"] = relationship("Multa", back_populates="prestamo", uselist=False)


class Reserva(Base):
    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    titulo_id: Mapped[int] = mapped_column(Integer, ForeignKey("titulos.id"), nullable=False)
    lector_id: Mapped[int] = mapped_column(Integer, ForeignKey("lectores.id"), nullable=False)
    ejemplar_asignado_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ejemplares.id"), nullable=True)
    posicion_cola: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[EstadoReserva] = mapped_column(Enum(EstadoReserva), default=EstadoReserva.EN_COLA)
    fecha_solicitud: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fecha_disponible: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fecha_limite_retiro: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    titulo: Mapped["Titulo"] = relationship("Titulo", back_populates="reservas")  # noqa: F821
    lector: Mapped["Lector"] = relationship("Lector", back_populates="reservas")  # noqa: F821


class Multa(Base):
    __tablename__ = "multas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prestamo_id: Mapped[int] = mapped_column(Integer, ForeignKey("prestamos.id"), unique=True, nullable=False)
    lector_id: Mapped[int] = mapped_column(Integer, ForeignKey("lectores.id"), nullable=False)
    motivo: Mapped[MotivoMulta] = mapped_column(Enum(MotivoMulta), nullable=False)
    monto: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[EstadoMulta] = mapped_column(Enum(EstadoMulta), default=EstadoMulta.PENDIENTE)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prestamo: Mapped["Prestamo"] = relationship("Prestamo", back_populates="multa")
    lector: Mapped["Lector"] = relationship("Lector", back_populates="multas")  # noqa: F821
