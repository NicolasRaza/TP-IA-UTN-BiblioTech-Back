import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.deps import get_db, get_usuario_actual, require_bibliotecario
from app.models.usuario import Usuario
from app.models.libro import Titulo, Ejemplar, EstadoValidacion, EstadoEjemplar
from app.schemas.libro import (
    TituloCreate, TituloUpdate, TituloValidar,
    TituloResponse, EjemplarCreate, EjemplarResponse, OCRResultado,
)
from app.agents.agente_captura import AgenteCaptura
from app.agents.agente_analizador import AgenteAnalizador
from app.agents.repositorios_impl import RepoConfig

router = APIRouter(prefix="/catalogo", tags=["Catálogo"])


# ── Títulos ───────────────────────────────────────────────────────────────────

@router.get("/titulos", response_model=list[TituloResponse], summary="Buscar títulos")
async def buscar_titulos(
    q: str | None = Query(None, description="Búsqueda por título, autor o ISBN"),
    genero: str | None = Query(None),
    solo_disponibles: bool = Query(False, description="Solo títulos con al menos un ejemplar disponible"),
    db: AsyncSession = Depends(get_db),
    _: Usuario = Depends(get_usuario_actual),
):
    """Disponible para lectores y bibliotecarios. Retorna solo títulos validados."""
    query = select(Titulo).where(Titulo.estado_validacion == EstadoValidacion.VALIDADO)

    if q:
        query = query.where(
            Titulo.titulo.ilike(f"%{q}%")
            | Titulo.autores.ilike(f"%{q}%")
            | Titulo.isbn.ilike(f"%{q}%")
        )
    if genero:
        query = query.where(Titulo.genero.ilike(f"%{genero}%"))

    result = await db.execute(query.order_by(Titulo.titulo))
    titulos = result.scalars().all()

    respuestas = []
    for t in titulos:
        total = await db.execute(
            select(func.count()).where(Ejemplar.titulo_id == t.id, Ejemplar.activo == True)
        )
        disponibles = await db.execute(
            select(func.count()).where(
                Ejemplar.titulo_id == t.id,
                Ejemplar.estado == EstadoEjemplar.DISPONIBLE,
                Ejemplar.activo == True,
            )
        )
        total_c = total.scalar()
        disp_c = disponibles.scalar()

        if solo_disponibles and disp_c == 0:
            continue

        r = TituloResponse.model_validate(t)
        r.total_ejemplares = total_c
        r.ejemplares_disponibles = disp_c
        respuestas.append(r)

    return respuestas


@router.get("/titulos/{titulo_id}", response_model=TituloResponse, summary="Detalle de título")
async def obtener_titulo(
    titulo_id: int,
    db: AsyncSession = Depends(get_db),
    _: Usuario = Depends(get_usuario_actual),
):
    result = await db.execute(select(Titulo).where(Titulo.id == titulo_id))
    titulo = result.scalar_one_or_none()
    if not titulo:
        raise HTTPException(status_code=404, detail="Título no encontrado")

    total = await db.execute(
        select(func.count()).where(Ejemplar.titulo_id == titulo_id, Ejemplar.activo == True)
    )
    disponibles = await db.execute(
        select(func.count()).where(
            Ejemplar.titulo_id == titulo_id,
            Ejemplar.estado == EstadoEjemplar.DISPONIBLE,
            Ejemplar.activo == True,
        )
    )
    r = TituloResponse.model_validate(titulo)
    r.total_ejemplares = total.scalar()
    r.ejemplares_disponibles = disponibles.scalar()
    return r


@router.post("/titulos/captura-ocr", response_model=OCRResultado,
             summary="Subir 3 fotos y obtener datos del libro (OCR + enriquecimiento)")
async def captura_ocr(
    foto_tapa: UploadFile = File(...),
    foto_contratapa: UploadFile = File(...),
    foto_ficha: UploadFile = File(..., description="Página con ISBN, autor y datos editoriales"),
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Agente de Captura: extrae texto de las 3 fotos con OCR.
    Agente Analizador: estructura los campos y enriquece con datos de internet por ISBN.
    El bibliotecario recibe la ficha sugerida para revisar y confirmar antes de guardar.
    """
    tapa_bytes = await foto_tapa.read() if foto_tapa else b""
    contratapa_bytes = await foto_contratapa.read() if foto_contratapa else b""
    ficha_bytes = await foto_ficha.read() if foto_ficha else b""

    # Agente de Captura (OCR)
    captura = AgenteCaptura()
    resultado_tapa = await captura.procesar_imagen_ocr(tapa_bytes) if tapa_bytes else {"texto_crudo": "", "isbn_detectado": None}
    resultado_contratapa = await captura.procesar_imagen_ocr(contratapa_bytes) if contratapa_bytes else {"texto_crudo": "", "isbn_detectado": None}
    resultado_ficha = await captura.procesar_imagen_ocr(ficha_bytes) if ficha_bytes else {"texto_crudo": "", "isbn_detectado": None}

    textos = [
        resultado_ficha["texto_crudo"],
        resultado_tapa["texto_crudo"],
        resultado_contratapa["texto_crudo"],
    ]
    texto_combinado = "\n\n".join(t for t in textos if t)
    isbn_detectado = (
        resultado_ficha.get("isbn_detectado")
        or resultado_tapa.get("isbn_detectado")
        or resultado_contratapa.get("isbn_detectado")
        or ""
    )

    # Agente Analizador (estructuración + enriquecimiento por ISBN)
    analizador = AgenteAnalizador(config_repo=RepoConfig())
    datos_ocr = analizador.procesar_texto_ocr(texto_combinado)
    resultado_enriq = await analizador.enriquecer(isbn_detectado, datos_ocr, texto_combinado)

    # Verificar si el ISBN ya existe en el catálogo
    # Construir OCRResultado desde el dict devuelto por el nuevo AgenteAnalizador
    def _val(campo): return (resultado_enriq.get(campo) or {}).get("valor", "") or ""
    def _conf(campo): return (resultado_enriq.get(campo) or {}).get("confianza", 0) or 0
    from app.schemas.libro import OCRResultado
    resultado = OCRResultado(
        isbn=_val("isbn") or None,
        titulo=_val("titulo") or None,
        autores=_val("autor") or None,
        editorial=_val("editorial") or None,
        anio_edicion=_val("anio") or None,
        lugar_edicion=_val("lugar") or None,
        sinopsis=_val("sinopsis") or None,
        genero=_val("genero") or None,
        portada_url=_val("portada") or None,
        paginas=int(_val("paginas")) if _val("paginas").isdigit() else None,
        confianza_isbn=_conf("isbn") / 100,
        confianza_titulo=_conf("titulo") / 100,
        confianza_autores=_conf("autor") / 100,
    )
    if resultado.isbn:
        existe = await db.execute(select(Titulo).where(Titulo.isbn == resultado.isbn))
        titulo_existente = existe.scalar_one_or_none()
        if titulo_existente:
            resultado.titulo_ya_existe = True
            resultado.titulo_existente_id = titulo_existente.id

    return resultado


@router.post("/titulos", response_model=TituloResponse, status_code=201,
             summary="Confirmar alta de título (después de revisar OCR)")
async def crear_titulo(
    data: TituloCreate,
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    El bibliotecario confirmó y corrigió los datos sugeridos por el OCR.
    El título queda en estado PENDIENTE hasta que se valide explícitamente.
    """
    if data.isbn:
        existe = await db.execute(select(Titulo).where(Titulo.isbn == data.isbn))
        if existe.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Ya existe un título con ese ISBN")

    titulo = Titulo(**data.model_dump(), creado_por_id=bibliotecario.id)
    db.add(titulo)
    await db.commit()
    await db.refresh(titulo)

    r = TituloResponse.model_validate(titulo)
    r.total_ejemplares = 0
    r.ejemplares_disponibles = 0
    return r


@router.post("/titulos/{titulo_id}/validar", response_model=TituloResponse,
             summary="Validar título (publicarlo en el catálogo)")
async def validar_titulo(
    titulo_id: int,
    data: TituloValidar,
    bibliotecario: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """
    Regla de negocio clave: ningún libro se publica sin confirmación explícita del bibliotecario,
    aunque la IA tenga 100% de confianza.
    """
    from datetime import datetime
    result = await db.execute(select(Titulo).where(Titulo.id == titulo_id))
    titulo = result.scalar_one_or_none()
    if not titulo:
        raise HTTPException(status_code=404, detail="Título no encontrado")

    for campo, valor in data.model_dump(exclude_none=True).items():
        setattr(titulo, campo, valor)

    titulo.estado_validacion = EstadoValidacion.VALIDADO
    titulo.validado_en = datetime.utcnow()
    await db.commit()
    await db.refresh(titulo)

    r = TituloResponse.model_validate(titulo)
    r.total_ejemplares = 0
    r.ejemplares_disponibles = 0
    return r


@router.patch("/titulos/{titulo_id}", response_model=TituloResponse, summary="Editar título")
async def editar_titulo(
    titulo_id: int,
    data: TituloUpdate,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Titulo).where(Titulo.id == titulo_id))
    titulo = result.scalar_one_or_none()
    if not titulo:
        raise HTTPException(status_code=404, detail="Título no encontrado")

    for campo, valor in data.model_dump(exclude_none=True).items():
        setattr(titulo, campo, valor)

    await db.commit()
    await db.refresh(titulo)

    r = TituloResponse.model_validate(titulo)
    r.total_ejemplares = 0
    r.ejemplares_disponibles = 0
    return r


# ── Ejemplares ────────────────────────────────────────────────────────────────

@router.post("/ejemplares", response_model=EjemplarResponse, status_code=201,
             summary="Agregar ejemplar a un título existente")
async def crear_ejemplar(
    data: EjemplarCreate,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """Genera un QR único para el ejemplar. El bibliotecario lo imprime en etiquetadora."""
    result = await db.execute(select(Titulo).where(Titulo.id == data.titulo_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Título no encontrado")

    codigo_qr = f"SGB-{uuid.uuid4().hex[:12].upper()}"
    ejemplar = Ejemplar(
        titulo_id=data.titulo_id,
        codigo_qr=codigo_qr,
        condicion=data.condicion,
        ubicacion_fisica=data.ubicacion_fisica,
    )
    db.add(ejemplar)
    await db.commit()
    await db.refresh(ejemplar)
    return ejemplar


@router.get("/ejemplares/qr/{codigo_qr}", response_model=EjemplarResponse,
            summary="Buscar ejemplar por código QR")
async def buscar_por_qr(
    codigo_qr: str,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Ejemplar).where(Ejemplar.codigo_qr == codigo_qr))
    ejemplar = result.scalar_one_or_none()
    if not ejemplar:
        raise HTTPException(status_code=404, detail="Ejemplar no encontrado")
    return ejemplar


@router.delete("/ejemplares/{ejemplar_id}", summary="Baja de ejemplar")
async def baja_ejemplar(
    ejemplar_id: int,
    _: Usuario = Depends(require_bibliotecario),
    db: AsyncSession = Depends(get_db),
):
    """Baja lógica. Conserva el historial de préstamos."""
    result = await db.execute(select(Ejemplar).where(Ejemplar.id == ejemplar_id))
    ejemplar = result.scalar_one_or_none()
    if not ejemplar:
        raise HTTPException(status_code=404, detail="Ejemplar no encontrado")

    if ejemplar.estado == EstadoEjemplar.PRESTADO:
        raise HTTPException(status_code=409, detail="El ejemplar está prestado actualmente")

    ejemplar.activo = False
    ejemplar.estado = EstadoEjemplar.BAJA
    await db.commit()
    return {"mensaje": "Ejemplar dado de baja", "codigo_qr": ejemplar.codigo_qr}
