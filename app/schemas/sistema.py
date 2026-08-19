"""Contratos HTTP de notificaciones, auditoría, configuración y aprendizaje."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.sistema import TipoNotificacion


# ── Notificaciones ────────────────────────────────────────────────────────────

class NotificacionCreate(BaseModel):
    lector_id: int
    tipo: TipoNotificacion
    titulo: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(min_length=1)


class NotificacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lector_id: int
    tipo: TipoNotificacion
    titulo: str
    descripcion: str
    leida: bool
    creado_en: datetime


# ── Auditoría ─────────────────────────────────────────────────────────────────

class EventoAuditoriaCreate(BaseModel):
    tipo: str = Field(min_length=1, max_length=40)
    descripcion: str = Field(min_length=1)


class EventoAuditoriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    descripcion: str
    usuario_id: Optional[int] = None
    creado_en: datetime


# ── Configuración ─────────────────────────────────────────────────────────────

# Los mapas por categoría se validan como `str -> int` y no contra un Enum:
# las categorías del dominio del cliente (`menor`, `senior`) no son las mismas
# que las de la base, y la traducción entre las dos escalas ya vive del lado de
# la app. Acá lo que importa es que ningún plazo ni límite sea absurdo.
MapaPorCategoria = dict[str, int]


class ConfiguracionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plazo_prestamo_dias: MapaPorCategoria
    limite_ejemplares: MapaPorCategoria
    limite_reservas: MapaPorCategoria
    plazo_retiro_reserva_horas: int
    multa_por_dia_demora: int
    recordatorio_antes_dias: int
    peso_historial_recomendacion: float
    min_prestamos_para_historial: int
    edad_mayoria_edad: int
    actualizado_en: datetime


class ConfiguracionUpdate(BaseModel):
    plazo_prestamo_dias: MapaPorCategoria
    limite_ejemplares: MapaPorCategoria
    limite_reservas: MapaPorCategoria
    plazo_retiro_reserva_horas: int = Field(ge=1, le=720)
    multa_por_dia_demora: int = Field(ge=0)
    recordatorio_antes_dias: int = Field(ge=0, le=30)
    peso_historial_recomendacion: float = Field(ge=0, le=1)
    min_prestamos_para_historial: int = Field(ge=0)
    edad_mayoria_edad: int = Field(ge=1, le=99)

    @field_validator("plazo_prestamo_dias", "limite_ejemplares", "limite_reservas")
    @classmethod
    def valores_positivos(cls, v: MapaPorCategoria) -> MapaPorCategoria:
        # Un plazo o un límite en cero deja a esa categoría sin poder operar, y
        # el error aparecería recién en el mostrador, como un préstamo que se
        # niega sin motivo visible. Se rechaza acá.
        if not v:
            raise ValueError("El mapa por categoría no puede estar vacío")
        for categoria, valor in v.items():
            if valor < 1:
                raise ValueError(
                    f"El valor de '{categoria}' debe ser al menos 1, llegó {valor}"
                )
        return v


# ── Aprendizaje ───────────────────────────────────────────────────────────────

class InteraccionCreate(BaseModel):
    lector_id: int
    titulo_id: int
    tipo: str = Field(min_length=1, max_length=30)


class InteraccionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lector_id: int
    titulo_id: int
    tipo: str
    creado_en: datetime


class CorreccionCreate(BaseModel):
    campo: str = Field(min_length=1, max_length=50)
    valor_sugerido: str
    valor_final: str


class CorreccionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campo: str
    valor_sugerido: str
    valor_final: str
    usuario_id: Optional[int] = None
    creado_en: datetime
