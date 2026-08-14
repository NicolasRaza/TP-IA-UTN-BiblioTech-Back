from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.libro import EstadoValidacion, EstadoEjemplar, CondicionFisica


# ── Titulo ────────────────────────────────────────────────────────────────────

class TituloCreate(BaseModel):
    isbn: Optional[str] = None
    titulo: str
    autores: str
    editorial: Optional[str] = None
    anio_edicion: Optional[str] = None
    lugar_edicion: Optional[str] = None
    idioma: Optional[str] = None
    genero: Optional[str] = None
    sinopsis: Optional[str] = None
    portada_url: Optional[str] = None
    paginas: Optional[int] = None


class TituloUpdate(BaseModel):
    titulo: Optional[str] = None
    autores: Optional[str] = None
    editorial: Optional[str] = None
    anio_edicion: Optional[str] = None
    lugar_edicion: Optional[str] = None
    idioma: Optional[str] = None
    genero: Optional[str] = None
    sinopsis: Optional[str] = None
    portada_url: Optional[str] = None
    paginas: Optional[int] = None


class TituloValidar(BaseModel):
    """Payload para que el bibliotecario valide o corrija los datos sugeridos por el OCR."""
    titulo: str
    autores: str
    editorial: Optional[str] = None
    anio_edicion: Optional[str] = None
    lugar_edicion: Optional[str] = None
    idioma: Optional[str] = None
    genero: Optional[str] = None
    sinopsis: Optional[str] = None
    portada_url: Optional[str] = None
    paginas: Optional[int] = None


class TituloResponse(BaseModel):
    id: int
    isbn: Optional[str]
    titulo: str
    autores: str
    editorial: Optional[str]
    anio_edicion: Optional[str]
    lugar_edicion: Optional[str]
    idioma: Optional[str]
    genero: Optional[str]
    sinopsis: Optional[str]
    portada_url: Optional[str]
    paginas: Optional[int]
    estado_validacion: EstadoValidacion
    total_ejemplares: int = 0
    ejemplares_disponibles: int = 0
    creado_en: datetime

    model_config = {"from_attributes": True}


# ── Ejemplar ──────────────────────────────────────────────────────────────────

class EjemplarCreate(BaseModel):
    titulo_id: int
    condicion: CondicionFisica = CondicionFisica.NUEVO
    ubicacion_fisica: Optional[str] = None


class EjemplarResponse(BaseModel):
    id: int
    titulo_id: int
    codigo_qr: str
    condicion: CondicionFisica
    estado: EstadoEjemplar
    ubicacion_fisica: Optional[str]
    activo: bool
    fecha_ingreso: datetime

    model_config = {"from_attributes": True}


# ── OCR / Captura ─────────────────────────────────────────────────────────────

class OCRResultado(BaseModel):
    """Datos extraídos automáticamente de las 3 fotos. El bibliotecario los revisa antes de confirmar."""
    isbn: Optional[str] = None
    titulo: Optional[str] = None
    autores: Optional[str] = None
    editorial: Optional[str] = None
    anio_edicion: Optional[str] = None
    lugar_edicion: Optional[str] = None
    # Nivel de confianza por campo (0.0 - 1.0)
    confianza_isbn: float = 0.0
    confianza_titulo: float = 0.0
    confianza_autores: float = 0.0
    # Datos enriquecidos del agente de búsqueda
    sinopsis: Optional[str] = None
    genero: Optional[str] = None
    portada_url: Optional[str] = None
    paginas: Optional[int] = None
    titulo_ya_existe: bool = False
    titulo_existente_id: Optional[int] = None
