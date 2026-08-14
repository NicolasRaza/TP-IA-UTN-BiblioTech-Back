import enum
from datetime import datetime
from sqlalchemy import String, Boolean, Enum, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class EstadoValidacion(str, enum.Enum):
    PENDIENTE = "pendiente_revision"
    VALIDADO = "validado"


class EstadoEjemplar(str, enum.Enum):
    DISPONIBLE = "disponible"
    PRESTADO = "prestado"
    RESERVADO = "reservado"
    BAJA = "baja"


class CondicionFisica(str, enum.Enum):
    NUEVO = "nuevo"
    BUENO = "bueno"
    REGULAR = "regular"
    DETERIORADO = "deteriorado"


class Titulo(Base):
    __tablename__ = "titulos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    isbn: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    autores: Mapped[str] = mapped_column(String(500), nullable=False)
    editorial: Mapped[str | None] = mapped_column(String(200), nullable=True)
    anio_edicion: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lugar_edicion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idioma: Mapped[str | None] = mapped_column(String(50), nullable=True)
    genero: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sinopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    portada_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paginas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado_validacion: Mapped[EstadoValidacion] = mapped_column(
        Enum(EstadoValidacion), default=EstadoValidacion.PENDIENTE
    )
    creado_por_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    validado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    ejemplares: Mapped[list["Ejemplar"]] = relationship("Ejemplar", back_populates="titulo")
    reservas: Mapped[list["Reserva"]] = relationship("Reserva", back_populates="titulo")  # noqa: F821


class Ejemplar(Base):
    __tablename__ = "ejemplares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    titulo_id: Mapped[int] = mapped_column(Integer, ForeignKey("titulos.id"), nullable=False)
    codigo_qr: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    condicion: Mapped[CondicionFisica] = mapped_column(Enum(CondicionFisica), default=CondicionFisica.NUEVO)
    estado: Mapped[EstadoEjemplar] = mapped_column(Enum(EstadoEjemplar), default=EstadoEjemplar.DISPONIBLE)
    ubicacion_fisica: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    fecha_ingreso: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    titulo: Mapped["Titulo"] = relationship("Titulo", back_populates="ejemplares")
    prestamos: Mapped[list["Prestamo"]] = relationship("Prestamo", back_populates="ejemplar")  # noqa: F821
