import enum
from datetime import date, datetime
from sqlalchemy import String, Boolean, Enum, Date, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class RolUsuario(str, enum.Enum):
    LECTOR = "lector"
    BIBLIOTECARIO = "bibliotecario"
    ADMINISTRADOR = "administrador"


class CategoriaLector(str, enum.Enum):
    INFANTIL = "infantil"
    ADOLESCENTE = "adolescente"
    ADULTO = "adulto"
    DOCENTE = "docente"
    INSTITUCIONAL = "institucional"


class EstadoUsuario(str, enum.Enum):
    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"
    BAJA = "baja"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[RolUsuario] = mapped_column(Enum(RolUsuario), default=RolUsuario.LECTOR)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    firebase_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lector: Mapped["Lector | None"] = relationship("Lector", back_populates="usuario", uselist=False)


class Lector(Base):
    __tablename__ = "lectores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False)
    documento: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    fecha_nacimiento: Mapped[date] = mapped_column(Date, nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    domicilio: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoria: Mapped[CategoriaLector] = mapped_column(Enum(CategoriaLector), default=CategoriaLector.ADULTO)
    # Todo lector nuevo entra SUSPENDIDO: el autorregistro (POST /lectores/) es
    # público y sin token, así que la verificación queda en manos del
    # bibliotecario, que lo pasa a ACTIVO desde el PATCH existente.
    estado: Mapped[EstadoUsuario] = mapped_column(Enum(EstadoUsuario), default=EstadoUsuario.SUSPENDIDO)
    tutor_nombre: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tutor_telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)
    consentimiento_datos: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_alta: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    usuario: Mapped["Usuario | None"] = relationship("Usuario", back_populates="lector")
    prestamos: Mapped[list["Prestamo"]] = relationship("Prestamo", back_populates="lector")  # noqa: F821
    reservas: Mapped[list["Reserva"]] = relationship("Reserva", back_populates="lector")  # noqa: F821
    multas: Mapped[list["Multa"]] = relationship("Multa", back_populates="lector")  # noqa: F821
