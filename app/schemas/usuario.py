from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
from app.models.usuario import RolUsuario, CategoriaLector, EstadoUsuario


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: RolUsuario


# ── Lector ────────────────────────────────────────────────────────────────────

class LectorCreate(BaseModel):
    nombre: str
    apellido: str
    documento: str
    fecha_nacimiento: date
    email: EmailStr
    telefono: Optional[str] = None
    domicilio: Optional[str] = None
    categoria: CategoriaLector = CategoriaLector.ADULTO
    tutor_nombre: Optional[str] = None
    tutor_telefono: Optional[str] = None
    consentimiento_datos: bool

    @field_validator("consentimiento_datos")
    @classmethod
    def debe_aceptar_consentimiento(cls, v: bool) -> bool:
        if not v:
            raise ValueError("El lector debe dar consentimiento de datos para registrarse")
        return v


class LectorUpdate(BaseModel):
    nombre: Optional[str] = None
    apellido: Optional[str] = None
    telefono: Optional[str] = None
    domicilio: Optional[str] = None
    categoria: Optional[CategoriaLector] = None
    estado: Optional[EstadoUsuario] = None
    tutor_nombre: Optional[str] = None
    tutor_telefono: Optional[str] = None


class LectorResponse(BaseModel):
    id: int
    nombre: str
    apellido: str
    documento: str
    fecha_nacimiento: date
    categoria: CategoriaLector
    estado: EstadoUsuario
    tutor_nombre: Optional[str]
    tutor_telefono: Optional[str]
    consentimiento_datos: bool
    fecha_alta: datetime
    usuario_id: Optional[int]

    model_config = {"from_attributes": True}


class LectorFichaResponse(LectorResponse):
    """Ficha completa del lector: incluye préstamos activos y multas pendientes."""
    prestamos_activos: int = 0
    multas_pendientes: int = 0


# ── Firebase token (para push notifications) ──────────────────────────────────

class FirebaseTokenUpdate(BaseModel):
    firebase_token: str
