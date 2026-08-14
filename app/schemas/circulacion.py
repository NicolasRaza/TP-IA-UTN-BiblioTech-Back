from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from app.models.circulacion import EstadoPrestamo, EstadoReserva, MotivoMulta, EstadoMulta


# ── Préstamo ──────────────────────────────────────────────────────────────────

class PrestamoCreate(BaseModel):
    """El bibliotecario escanea el QR del ejemplar y busca al lector."""
    qr_ejemplar: str
    lector_id: int


class DevolucionRequest(BaseModel):
    qr_ejemplar: str


class PrestamoResponse(BaseModel):
    id: int
    ejemplar_id: int
    lector_id: int
    fecha_inicio: date
    fecha_devolucion_pactada: date
    fecha_devolucion_real: Optional[date]
    estado: EstadoPrestamo
    dias_restantes: Optional[int] = None
    creado_en: datetime

    model_config = {"from_attributes": True}


# ── Reserva ───────────────────────────────────────────────────────────────────

class ReservaCreate(BaseModel):
    titulo_id: int


class ReservaResponse(BaseModel):
    id: int
    titulo_id: int
    lector_id: int
    posicion_cola: int
    estado: EstadoReserva
    fecha_solicitud: datetime
    fecha_disponible: Optional[datetime]
    fecha_limite_retiro: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Multa ─────────────────────────────────────────────────────────────────────

class MultaCreate(BaseModel):
    prestamo_id: int
    motivo: MotivoMulta
    monto: Optional[float] = None
    observaciones: Optional[str] = None


class MultaUpdate(BaseModel):
    estado: EstadoMulta
    observaciones: Optional[str] = None


class MultaResponse(BaseModel):
    id: int
    prestamo_id: int
    lector_id: int
    motivo: MotivoMulta
    monto: Optional[float]
    estado: EstadoMulta
    observaciones: Optional[str]
    creado_en: datetime

    model_config = {"from_attributes": True}


# ── Dashboard / Indicadores ───────────────────────────────────────────────────

class IndicadoresResponse(BaseModel):
    total_lectores_activos: int
    total_prestamos_activos: int
    total_prestamos_vencidos: int
    total_reservas_en_cola: int
    tasa_devolucion_tiempo: float
    top_titulos_prestados: list[dict]
    top_lectores_activos: list[dict]
