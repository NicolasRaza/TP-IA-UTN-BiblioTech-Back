"""
BiblioTech — Agente 2: Analizador y Enriquecimiento (agentes/agente_analizador.py)
===================================================================================
Migración de js/agents/agente-analizador.js

Reglas de negocio conservadas intactas:
  - Jerarquía de extracción de ISBN (nivel 1 estricto, nivel 2 tolerante OCR)
  - Jerarquía temporal de año de edición (edición actual > año reciente > copyright)
  - Extracción de páginas con dos patrones (etiqueta antes / número antes)
  - Lista de editoriales conocidas (misma lista)
  - Patrón de autor (regex nombre propio)
  - Filtro de ruido OCR para títulos
  - Enriquecimiento con Ollama (mismo prompt en español, timeout 45s, fallback)
  - Reglas de prioridad física (ISBN, año, páginas físicas preservados sobre la API)
  - Normalización de géneros
  - Fallback genérico de sinopsis construido desde párrafos del OCR
  - Función buscar_por_isbn inyectada (equivale a window.buscarPorISBN)

Cambios de plataforma:
  - fetch() → httpx.AsyncClient (en enriquecer_con_ollama)
  - window.capitalizar() → método local _capitalizar()
  - window.buscarPorISBN → parámetro inyectado buscar_por_isbn_fn
  - Sin acceso a window / localStorage
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Coroutine, Optional

import httpx

from .repositorios import RepositorioConfig

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS: float = 45.0

# Tipo de la función de búsqueda externa (análoga a window.buscarPorISBN)
BuscarPorISBNFn = Callable[
    [str, str, str],
    Coroutine[Any, Any, Optional[dict[str, Any]]],
]

# Campos editoriales canónicos
CAMPOS_EDITORIALES: list[str] = [
    "isbn", "titulo", "autor", "editorial",
    "anio", "lugar", "paginas", "genero", "sinopsis", "portada",
]

EDITORIALES_CONOCIDAS: list[str] = [
    "planeta", "artifex", "bibliópolis", "bibliopolis", "alamut", "minotauro", "nova",
    "gigamesh", "alianza", "cátedra", "catedra", "valdemar", "sudamericana", "emecé",
    "alfaguara", "anagrama", "seix barral", "tusquets", "debolsillo", "salamandra",
    "fondo de cultura", "debate", "crítica", "lumen", "alba", "suma", "random house",
    "siglo xxi", "norma", "paidós", "granica", "océano", "vergara", "urano", "siruela",
    "roca editorial", "ediciones b",
]

PALABRAS_RUIDO: list[str] = [
    "na de", "ool", "mo mo", "cdd", "4titul", "autóno", "autonoma",
    "derechos", "impreso", "depósito", "deposito", "ley 11",
    "reproducción", "reproduccion", "alquiler", "charlone", "avellaneda",
    "edición:", "edicion:", "ejemplares", "ejemplar de",
    "debería tener", "deberia tener", "autor de",
    "bestseller", "vendidos", "claves imperecederas",
    "traducción de", "traduccion de", "traductor",
    "fotocopias", "digitalización", "digitalizacion",
    "www.", "http",
    # Líneas de imprenta / pie de página
    "printed in", "impreso en", "print in", "hecho en",
    "queda prohibida", "queda rigurosamente", "todos los derechos",
    "sin permiso", "sin previo", "cualquier medio",
    "depósito legal", "deposito legal",
    "ibic:", "cdu:", "código:", "codigo:",
    "alcalá", "alcala", "luis g.", "editor@",
    "publicado por arrangement", "literary agency",
]


def _capitalizar(s: str) -> str:
    """Equivalente a la función capitalizar() de utils.js."""
    return s.capitalize() if s else s


def _limpiar_autor(autor: str) -> str:
    """
    Limpia y normaliza el formato del nombre de autor:
      - Elimina puntos parásitos e innecesarios (ej: 'ANDRZEJ. SAPKOWSKI' -> 'Andrzej Sapkowski').
      - Convierte mayúsculas sostenidas rígidas a Title Case respetando partículas y guiones.
    """
    if not autor:
        return ""
    # Limpiar espacios alrededor de guiones (ej. 'Saint - Exupéry' -> 'Saint-Exupéry')
    s = re.sub(r"\s*-\s*", "-", autor)
    # Quitar puntos parásitos tras palabras de 2 o más letras
    s = re.sub(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,})\.", r"\1", s).strip()
    s = re.sub(r"\s*\.\s*", " ", s).strip()
    s = re.sub(r"\s+", " ", s)

    # Si está en mayúsculas sostenidas, normalizar a Title Case respetando partículas y guiones
    if s.isupper() and len(s) > 3:
        particulas = {"de", "del", "la", "las", "los", "y", "van", "von", "der", "den", "di", "da"}
        palabras = s.split()
        palabras_formateadas = []
        for i, p in enumerate(palabras):
            p_lower = p.lower()
            if "-" in p:
                p_formateada = "-".join(part.capitalize() for part in p.split("-"))
            elif i > 0 and p_lower in particulas:
                p_formateada = p_lower
            else:
                p_formateada = p.capitalize()
            palabras_formateadas.append(p_formateada)
        s = " ".join(palabras_formateadas)
    return s


def _normalizar_genero(genero: str) -> str:
    """
    Normaliza clasificaciones de género:
      - Limpia prefijos y numeraciones CIP (ej. '1. Narrativa Francesa. I. Título. CDD 843' -> 'Narrativa Francesa').
      - Traduce y mapea términos genéricos en inglés hacia categorías bibliográficas precisas en español.
    """
    if not genero:
        return ""
    g = genero.strip()
    # Limpiar prefijos numéricos de ficha CIP y sufijos de catalogación
    g = re.sub(r"^\d+\.\s*", "", g)
    g = re.sub(r"\bCDD\s*\d+.*$", "", g, flags=re.IGNORECASE).strip()
    g = re.sub(r"\.\s*(?:I|II|III)\..*$", "", g).strip().rstrip(".")

    g_low = g.lower()
    # Mapeo de términos genéricos en inglés a categorías en español
    if g_low in ("fiction", "general fiction", "literary fiction", "novela"):
        return "Narrativa"
    if "fantasy" in g_low or "fantasía" in g_low or "fantasia" in g_low:
        return "Literatura Fantástica"
    if "science fiction" in g_low or "ciencia ficción" in g_low or "ciencia ficcion" in g_low:
        return "Ciencia Ficción"
    if any(k in g_low for k in ["personal finance", "finance", "finanzas", "dinero", "invers"]):
        return "Finanzas Personales"
    if any(k in g_low for k in ["self-help", "desarrollo personal", "autoayuda", "superacion"]):
        return "Desarrollo Personal"
    if any(k in g_low for k in ["thriller", "misterio", "policial", "detective", "suspense"]):
        return "Novela Policial / Thriller"
    if any(k in g_low for k in ["history", "historia", "ensayo"]):
        return "Historia / Ensayo"
    if any(k in g_low for k in ["juvenile fiction", "children", "infantil", "juvenil", "cuentos"]):
        return "Infantil / Juvenil"
    if "philosophy" in g_low or "filosofía" in g_low or "filosofia" in g_low:
        return "Filosofía"

    return _capitalizar(g) if len(g) > 2 else g


class AgenteAnalizador:
    """
    Agente 2 — Analizador y Enriquecimiento.

    Responsabilidades:
      - Parsear texto OCR con regex y heurísticas NLP.
      - Enriquecer datos con Ollama (IA local opcional).
      - Enriquecer datos con API externa (Google Books / OpenLibrary).

    Args:
        config_repo: Repositorio de configuración (para leer motorIaLocal,
                     ollamaEndpoint, ollamaModelo).
        buscar_por_isbn_fn: Función async análoga a window.buscarPorISBN del
                            frontend. Firma: async (isbn, autor, titulo) → dict | None.
                            Si es None, el paso de enriquecimiento por API se omite.
    """

    def __init__(
        self,
        config_repo: RepositorioConfig,
        buscar_por_isbn_fn: Optional[BuscarPorISBNFn] = None,
    ) -> None:
        self._config = config_repo
        self._buscar_por_isbn_fn = buscar_por_isbn_fn

    # ------------------------------------------------------------------
    # OCR Parsing
    # ------------------------------------------------------------------

    def _extraer_ficha_catalografica(self, texto: str) -> dict[str, str]:
        """
        Extrae metadatos de la ficha catalográfica (CIP / AACR2 / ISBD) si está presente.
        Formato típico argentino/español:
          Apellido, Nombre [Apellido2, Nombre2]

          Título del libro. Nº edición.
          Ciudad [Autónoma] de X : Editorial S.R.L., Año.
          Páginas p. : il. ; dim cm
          ISBN: xxx

          1. Género/Materia. I. Título.
        """
        ficha: dict[str, str] = {}
        if not texto:
            return ficha

        # ── 1. Línea ISBD: Título separado por " / " del autor ─────────────────
        # Ej: "Título del libro / Nombre Apellido. - 2a ed."
        # CRÍTICO: Rechazar si el candidato contiene ruido de imprenta
        RUIDO_ISBD = {
            "impreso", "printed", "isbn", "ejemplares", "ejemplar",
            "depósito", "deposito", "hecho en", "queda", "derechos",
            "www.", "http", "reservados",
        }
        m_isbd = re.search(
            r'([A-ZÁÉÍÓÚÜÑa-záéíóúüñ\s0-9:,\'"¿?¡!\-]{4,90}?)'
            r'\s*/\s*'
            r'([A-ZÁÉÍÓÚÜÑa-záéíóúüñ\s\-\.]{3,70}?)'
            r'(?:\s*\.\s*-|\s*—|\n|$)',
            texto,
        )
        if m_isbd:
            raw_tit = m_isbd.group(1).strip()
            raw_aut = m_isbd.group(2).strip()
            # En fichas CIP, la cabecera «Apellido, Nombre» suele estar en la línea anterior al título
            lineas_tit = [l.strip() for l in raw_tit.split("\n") if l.strip()]
            tit_cand = lineas_tit[-1] if lineas_tit else raw_tit
            aut_cand = raw_aut

            # Rechazar si alguno de los grupos es ruido de imprenta
            tit_low = tit_cand.lower()
            aut_low = aut_cand.lower()
            es_ruido_isbd = (
                any(k in tit_low for k in RUIDO_ISBD)
                or any(k in aut_low for k in RUIDO_ISBD)
                or any(k in aut_low for k in ["traducción", "traduccion", "edición", "editorial"])
                or re.search(r'\b(in|en)\s+(argentina|españa|mexico|chile)\b', tit_low)
                or re.search(r'\bISBN\b', tit_cand, re.IGNORECASE)
            )
            if not es_ruido_isbd:
                ficha["titulo"] = tit_cand
                ficha["autor"] = _limpiar_autor(aut_cand)

        # ── 2. Título en línea propia: "El Principito. Segunda edición." ────────
        # Busca una línea que tenga «Título. [Algo] edición.» o «Título.» sola
        if not ficha.get("titulo"):
            m_tit_solo = re.search(
                r'^([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑa-záéíóúüñ\s0-9:,\'"¿?¡!\-]{2,80}?)'
                r'\.\s*(?:Primera|Segunda|Tercera|Cuarta|Quinta|\d+[aª])?\s*[Ee]dición',
                texto,
                re.MULTILINE,
            )
            if m_tit_solo:
                tit_solo_cand = m_tit_solo.group(1).strip()
                if not any(k in tit_solo_cand.lower() for k in RUIDO_ISBD):
                    ficha["titulo"] = tit_solo_cand

        # ── 3. Autor CIP formato "Apellido, Nombre" (primera coincidencia válida) ─
        # Palabras que nunca son nombres de persona en un CIP
        PALABRAS_NO_PERSONA = {
            "editorial", "traduccion", "traducción", "derechos", "edicion", "edición",
            "impreso", "hecho", "ciudad", "buenos", "barcelona", "madrid",
            "titulo", "título", "narrativa", "catalogacion", "catalogación",
            "printed", "argentina", "españa", "mexico",
        }
        if not ficha.get("autor"):
            for m_aut in re.finditer(
                r'^\s*((?:de\s+|del\s+|von\s+|van\s+)?[A-ZÁÉÍÓÚÜÑ][A-Za-záéíóúüñ\s\-]+?),\s*'
                r'([A-ZÁÉÍÓÚÜÑ][A-Za-záéíóúüñ\s\-\.]+?)(?:\n|$)',
                texto,
                re.MULTILINE,
            ):
                apellido = m_aut.group(1).strip()
                nombre   = m_aut.group(2).strip()
                # Descartar si apellido o nombre son palabras de imprenta/ruido o contienen dígitos
                if (
                    apellido.lower() not in PALABRAS_NO_PERSONA
                    and not any(w in PALABRAS_NO_PERSONA for w in nombre.lower().split())
                    and not re.search(r"\d", apellido)
                    and len(apellido) > 2
                ):
                    ficha["autor"] = _limpiar_autor(f"{nombre} {apellido}")
                    break

        # ── 4. Editorial + Año: «Ciudad [Autónoma]: Editorial S.R.L., Año.» ────
        # Captura la editorial completa incluyendo siglas (S.R.L., S.A., etc.)
        m_pub = re.search(
            r':\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\.]+?)'
            r',\s*(\d{4})',
            texto,
        )
        if m_pub:
            ed_nombre = m_pub.group(1).strip().rstrip(".")
            CIUDADES = ["ciudad", "buenos aires", "españa", "mexico", "madrid", "barcelona",
                        "autónoma", "autonoma", "federal"]
            if len(ed_nombre) < 60 and not any(c in ed_nombre.lower() for c in CIUDADES):
                ficha["editorial"] = ed_nombre
            ficha["anio"] = m_pub.group(2).strip()

        # ── 5. Lugar de edición: ÚNICAMENTE desde línea CIP «Ciudad : Editorial, Año.» ─
        # No capturar desde direcciones de editorial (ej. "Barcelona" de "Av. Diagonal 662-664 Barcelona")
        # El patrón exige que la ciudad venga ANTES de ": Editorial, Año" en la misma línea CIP
        m_lugar_cip = re.search(
            r'^((?:Ciudad\s+Autónoma\s+de\s+)?[A-ZÁÉÍÓÚÜÑ][A-Za-záéíóúüñ\s]+?)\s*:\s*'
            r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\.]+?,\s*\d{4}',
            texto,
            re.MULTILINE,
        )
        if m_lugar_cip:
            lugar_cand = m_lugar_cip.group(1).strip()
            # Aceptar solo si parece un nombre de ciudad/localidad (no tiene comas, barras ni dígitos)
            if 4 < len(lugar_cand) < 80 and not re.search(r'[/,\d]', lugar_cand):
                ficha["lugar"] = lugar_cand

        # ── 6. Páginas: «96p.» o «312 p. ; 23 x 15 cm» ──────────────────────
        m_pag = re.search(r'\b(\d{2,4})\s*p\b', texto, re.IGNORECASE)
        if m_pag:
            ficha["paginas"] = m_pag.group(1)

        # ── 7. Género/Materia: «1. Narrativa Francesa. I. Título.» ─────────────
        m_mat = re.search(
            r'(?:^|\n)\s*1\.\s*([A-Za-záéíóúüñÁÉÍÓÚÜÑ][A-Za-záéíóúüñÁÉÍÓÚÜÑ\s/]+?)(?:\.|\s+I\.|\s+II\.|\n)',
            texto,
            re.MULTILINE,
        )
        if m_mat:
            genero_cand = _normalizar_genero(m_mat.group(1).strip())
            if len(genero_cand) > 3:
                ficha["genero"] = genero_cand

        return ficha

    def _extraer_sinopsis(self, texto_ocr: str) -> tuple[str, int]:
        """
        Extrae la sinopsis íntegra analizando prioritariamente el bloque de contratapa.
        Transcribe citas, reseñas y texto descriptivo, evitando devolver vacío/null si existe texto.
        """
        if not texto_ocr:
            return "", 0

        # 1. Buscar en el bloque identificado de CONTRATAPA
        bloque_contratapa = ""
        m_bloque = re.search(
            r"===\s*CONTRATAPA\s*(?:/\s*SINOPSIS)?\s*===\s*\n?(.*?)(?:\n===|\Z)",
            texto_ocr,
            re.DOTALL | re.IGNORECASE,
        )
        if m_bloque:
            bloque_contratapa = m_bloque.group(1).strip()

        texto_a_analizar = bloque_contratapa or texto_ocr

        # Filtrar líneas de ruido de imprenta / códigos de barras / ISBN
        lineas_sinopsis: list[str] = []
        for l in texto_a_analizar.split("\n"):
            l_str = l.strip()
            if not l_str:
                continue
            l_low = l_str.lower()
            # Ignorar encabezados de sección
            if l_str.startswith("===") or "portada" in l_low or "ficha catalográfica" in l_low:
                continue
            # Ignorar códigos de barras / ISBN / depósitos / códigos numéricos
            if re.search(r"\b(?:isbn|ibic|cdu|depósito|deposito)\b", l_low):
                continue
            if re.match(r"^[\d\s\-X]{8,}$", l_str):
                continue
            # Ignorar créditos de traducción o notas de imprenta si están aisladas
            if re.match(r"^(?:traducción|traduccion)\s+de\b", l_low) and len(l_str.split()) < 6:
                continue
            if len(l_str) < 3:
                continue
            # Ignorar encabezados visuales en mayúsculas (slogans/titulares de contratapa)
            # Ej: "LA RIQUEZA NO ES FRUTO DE NUESTRA INTELIGENCIA, TALENTO O TRABAJO"
            # Se identifican como líneas completamente en mayúsculas con 5 o más palabras
            if l_str.isupper() and len(l_str.split()) >= 5:
                continue
            # Ignorar líneas que son solo el nombre del logo editorial aislado
            if l_str.upper() == l_str and l_str.lower().strip() in EDITORIALES_CONOCIDAS:
                continue
            lineas_sinopsis.append(l_str)

        # Limpiar línea final si es únicamente el logo o editorial (ej. 'ARTIFEX', 'PLANETA')
        if lineas_sinopsis and lineas_sinopsis[-1].lower().strip() in EDITORIALES_CONOCIDAS:
            lineas_sinopsis.pop()

        if lineas_sinopsis:
            sinopsis_limpia = " ".join(lineas_sinopsis).strip()
            if len(sinopsis_limpia) > 25:
                return sinopsis_limpia, 85 if bloque_contratapa else 70

        return "", 0

    def procesar_texto_ocr(self, texto_ocr: str) -> dict[str, Any]:
        """
        Analiza el texto OCR crudo aplicando expresiones regulares y
        heurísticas NLP.

        Args:
            texto_ocr: Texto extraído por OCR.

        Returns:
            Diccionario con campos editoriales estructurados y porcentaje
            de confianza. Cada campo es {'valor': str, 'confianza': int}.
        """
        if not texto_ocr:
            texto_ocr = ""

        lineas: list[str] = [l.strip() for l in texto_ocr.split("\n") if l.strip()]

        resultado: dict[str, Any] = {
            "isbn":      {"valor": "", "confianza": 0},
            "titulo":    {"valor": "", "confianza": 0},
            "autor":     {"valor": "", "confianza": 0},
            "editorial": {"valor": "", "confianza": 0},
            "anio":      {"valor": "", "confianza": 0},
            "lugar":     {"valor": "", "confianza": 0},
            "paginas":   {"valor": "", "confianza": 0},
            "genero":    {"valor": "", "confianza": 0},
            "sinopsis":  {"valor": "", "confianza": 0},
        }

        # 0. Ficha catalográfica / CIP (ISBD) — Máxima prioridad física
        cip = self._extraer_ficha_catalografica(texto_ocr)
        if cip.get("titulo"):
            resultado["titulo"] = {"valor": cip["titulo"], "confianza": 95, "fuente": "CIP"}
        if cip.get("autor"):
            resultado["autor"] = {"valor": cip["autor"], "confianza": 95, "fuente": "CIP"}
        if cip.get("editorial"):
            resultado["editorial"] = {"valor": cip["editorial"], "confianza": 95, "fuente": "CIP"}
        if cip.get("anio"):
            resultado["anio"] = {"valor": cip["anio"], "confianza": 95, "fuente": "CIP"}
        if cip.get("paginas"):
            resultado["paginas"] = {"valor": cip["paginas"], "confianza": 92, "fuente": "CIP"}
        if cip.get("genero"):
            resultado["genero"] = {"valor": cip["genero"], "confianza": 90, "fuente": "CIP"}
        # Lugar de edición desde CIP
        if cip.get("lugar"):
            resultado["lugar"] = {"valor": cip["lugar"], "confianza": 92, "fuente": "CIP"}

        # 1. ISBN — Extracción tolerante a errores OCR
        isbn_valor, isbn_confianza = self._extraer_isbn(texto_ocr)
        if isbn_valor:
            logger.debug("[AgenteAnalizador] ISBN detectado: %s (confianza: %d%%)", isbn_valor, isbn_confianza)
            resultado["isbn"] = {"valor": isbn_valor, "confianza": isbn_confianza}

        # 2. Año de Publicación (busca la edición/reimpresión más reciente)
        anio_valor, anio_confianza = self._extraer_anio(texto_ocr)
        if anio_valor and (not resultado["anio"]["valor"] or int(anio_valor) >= int(resultado["anio"]["valor"] or 0)):
            resultado["anio"] = {"valor": anio_valor, "confianza": anio_confianza}

        # 3. Páginas si no estaba en CIP
        if not resultado["paginas"]["valor"]:
            paginas_valor, paginas_confianza = self._extraer_paginas(texto_ocr)
            if paginas_valor:
                resultado["paginas"] = {"valor": paginas_valor, "confianza": paginas_confianza}

        # 4. Editorial
        if not resultado["editorial"]["valor"]:
            # Pasar el autor ya detectado para evitar confundir apellido de autor con editorial
            autor_ya_detectado = resultado.get("autor", {}).get("valor", "")
            editorial_valor, editorial_confianza = self._extraer_editorial(lineas, texto_ocr, autor_ya_detectado)
            if editorial_valor:
                resultado["editorial"] = {"valor": editorial_valor, "confianza": editorial_confianza}

        # 5. Autor
        if not resultado["autor"]["valor"]:
            autor_valor, autor_confianza = self._extraer_autor(lineas)
            if autor_valor:
                resultado["autor"] = {"valor": autor_valor, "confianza": autor_confianza}

        # 6. Título
        if not resultado["titulo"]["valor"]:
            titulo_valor, titulo_confianza = self._extraer_titulo(lineas, resultado.get("autor", {}).get("valor", ""))
            if titulo_valor:
                resultado["titulo"] = {"valor": titulo_valor, "confianza": titulo_confianza}

        # 7. Lugar de edición (solo si no fue ya asignado desde CIP)
        if not resultado["lugar"]["valor"]:
            lugar_valor, lugar_confianza = self._extraer_lugar(texto_ocr)
            if lugar_valor:
                resultado["lugar"] = {"valor": lugar_valor, "confianza": lugar_confianza}

        # 8. Sinopsis (analizando bloque de contratapa / párrafos descriptivos)
        if not resultado["sinopsis"]["valor"]:
            sinopsis_val, sinopsis_conf = self._extraer_sinopsis(texto_ocr)
            if sinopsis_val:
                resultado["sinopsis"] = {"valor": sinopsis_val, "confianza": sinopsis_conf}

        return resultado

    def _extraer_isbn(self, texto: str) -> tuple[str, int]:
        """ISBN — niveles de confianza decreciente y robusto contra saltos de línea."""
        if not texto:
            return "", 0

        # Nivel 1: Con prefijo explícito (ISBN, ISBN-13, 1SBN, I.S.B.N.)
        patron_prefijo = re.compile(
            r"(?:(?:ISBN(?:-?1[03])?|1SBN|I\.?S\.?B\.?N\.?)[:.\s]*)\s*([0-9\-\s]{10,22}[0-9X])\b",
            re.IGNORECASE,
        )
        for m in patron_prefijo.finditer(texto):
            raw = m.group(1)
            limpio = re.sub(r"[^0-9X]", "", raw.upper())
            if len(limpio) == 13 and limpio.startswith(("978", "979")):
                return limpio, 98
            if len(limpio) == 10:
                return limpio, 95
            if len(limpio) > 13 and limpio.startswith(("978", "979")):
                return limpio[:13], 92

        # Nivel 2: Formato estándar 978/979
        patron_isbn13 = re.compile(r"\b(97[89][0-9\-\s]{10,18})\b")
        for m in patron_isbn13.finditer(texto):
            raw = m.group(1)
            limpio = re.sub(r"[^0-9]", "", raw)
            if len(limpio) == 13:
                return limpio, 90
            if len(limpio) > 13 and limpio.startswith(("978", "979")):
                return limpio[:13], 85

        # Nivel 3: Secuencia tolerante a errores OCR
        candidatos = re.findall(r"[\d][\d\s\-]{9,20}[\dX]", texto, re.IGNORECASE)
        for c in candidatos:
            digits = re.sub(r"[^0-9X]", "", c.upper())
            if len(digits) == 13 and digits.startswith(("978", "979")):
                return digits, 80
            if len(digits) == 10:
                return digits, 75
            if len(digits) == 13 and (digits.startswith("078") or digits.startswith("079")):
                return "9" + digits[1:], 65
            if len(digits) == 12 and digits.startswith("78"):
                return "9" + digits, 60

        return "", 0

    def _extraer_anio(self, texto: str) -> tuple[str, int]:
        """Año — Jerarquía Temporal: busca la edición, reimpresión o tirada más reciente."""
        if not texto:
            return "", 0

        anios_menciones: list[int] = []

        # 1. Menciones explícitas de edición, reimpresión, depósito legal o copyright actual
        for m in re.finditer(
            r"(?:edición|reimpresión|impreso|publicad[oa]|tirada|depósito legal|deposito legal)[^\n\d]{0,60}\b(19[89]\d|20[0-2]\d)\b",
            texto,
            re.IGNORECASE,
        ):
            anios_menciones.append(int(m.group(1)))

        # 2. Meses acompañados de año (ej. 'octubre de 2016')
        for m in re.finditer(
            r"\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\b(19[89]\d|20[0-2]\d)\b",
            texto,
            re.IGNORECASE,
        ):
            anios_menciones.append(int(m.group(1)))

        # 3. Copyright de editoriales/sello: © 2016 Artifex
        for m in re.finditer(r"©\s*(19[89]\d|20[0-2]\d)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)", texto, re.IGNORECASE):
            entidad = m.group(2).lower()
            if entidad not in ("traducción", "traduccion", "por"):
                anios_menciones.append(int(m.group(1)))

        if anios_menciones:
            anio_max = max(anios_menciones)
            logger.debug("[AgenteAnalizador] Año más reciente detectado: %s", anio_max)
            return str(anio_max), 95

        # Fallback a cualquier año 1980-2029
        todos_anios = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-2]\d)\b", texto)]
        if todos_anios:
            return str(max(todos_anios)), 70

        return "", 0

    def _extraer_lugar(self, texto: str) -> tuple[str, int]:
        """Extrae el lugar de edición (Ciudad) priorizando la línea CIP."""
        if not texto:
            return "", 0

        # Prioridad 1: Línea CIP completa «Ciudad Autónoma de Buenos Aires : Editorial, Año»
        m_cip = re.search(
            r'^((?:Ciudad\s+Autónoma\s+de\s+Buenos\s+Aires|Buenos\s+Aires|Rosario|Córdoba|Mendoza|'
            r'Ciudad\s+de\s+México|Bogotá|Santiago|Lima|Madrid|Barcelona)[A-Za-záéíóúüñ\s]*?)'
            r'\s*:\s*[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\.]+?,\s*\d{4}',
            texto,
            re.MULTILINE,
        )
        if m_cip:
            lugar_cip = m_cip.group(1).strip()
            if 4 < len(lugar_cip) < 80 and not re.search(r'[/,\d]', lugar_cip):
                return lugar_cip, 92

        # Prioridad 2: Buscar "Publicado bajo el sello X / Av. X, Ciudad"
        # o patrón "Av. X, CABA / Ciudad Autónoma"
        m_caba = re.search(r'\b(Ciudad\s+Autónoma\s+de\s+Buenos\s+Aires|C\.?\s*A\.?\s*B\.?\s*A\.?)\b', texto, re.IGNORECASE)
        if m_caba:
            return "Ciudad Autónoma de Buenos Aires", 88

        # Prioridad 3: Solo ciudad (sin combinar con país para evitar "Barcelona, Argentina")
        # Ignorar "Barcelona" si también hay "Argentina" (evitar mezclar ciudad española con país argentino)
        hay_argentina = bool(re.search(r'\bargentina\b', texto, re.IGNORECASE))
        hay_barcelona = bool(re.search(r'\bbarcelona\b', texto, re.IGNORECASE))

        if not (hay_barcelona and hay_argentina):
            if re.search(r'\bmadrid\b', texto, re.IGNORECASE):
                return "Madrid", 80
            if re.search(r'\bbarcelona\b', texto, re.IGNORECASE):
                return "Barcelona", 80

        if re.search(r'\bbuenos aires\b', texto, re.IGNORECASE):
            return "Buenos Aires", 75
        if re.search(r'\bméxico|mexico d\.?f\.?|ciudad de méxico\b', texto, re.IGNORECASE):
            return "Ciudad de México", 75

        return "", 0

    def _extraer_paginas(self, texto: str) -> tuple[str, int]:
        """Páginas — formato catalográfico '312 p.' o etiqueta antes / número antes."""
        # 1. Formato catalográfico: '312 p. ; 23 x 15 cm' o '312 p.'
        m = re.search(r"\b(\d{2,4})\s*p\b(?:\s*[\.;,]|\s*\d+\s*x|$)", texto, re.IGNORECASE)
        if m:
            return m.group(1), 92

        # 2. Etiqueta antes: 'páginas: 312'
        m = re.search(r"(?:páginas?|pags?|pp\.?|paginas?)\s*[:.]?\s*(\d{1,4})(?:\s*p\b)?", texto, re.IGNORECASE)
        if m:
            return m.group(1), 85

        # 3. Número antes: '312 páginas'
        m = re.search(r"\b(\d{2,4})\s*(?:páginas|paginas|pags|pp)\b", texto, re.IGNORECASE)
        if m:
            return m.group(1), 85

        return "", 0

    def _extraer_editorial(self, lineas: list[str], texto_ocr: str = "", autor_candidato: str = "") -> tuple[str, int]:
        """
        Editorial — Da prioridad al sello o logo que aparece en la portada o en la página
        de legales/derechos de autor de la edición física actual visible.
        """
        # 1. Buscar mención de última edición física: e.g. "Quinta edición y primera edición en Artifex: octubre de 2016"
        cand_edicion = ""
        if texto_ocr:
            for m in re.finditer(
                r'(?:primera\s+edición|segunda\s+edición|tercera\s+edición|cuarta\s+edición|quinta\s+edición|\d+[aª]\s+edición|edición)\s+en\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+?)(?:\s*\([^\)]*\))?\s*:',
                texto_ocr,
                re.IGNORECASE,
            ):
                cand = m.group(1).strip()
                if len(cand) > 2 and cand.lower() not in ("rústica", "rustica", "cartoné", "cartone", "tapa"):
                    cand_edicion = _capitalizar(cand)
        if cand_edicion:
            return cand_edicion, 94

        # 2. Buscar en Ficha CIP: ": Editorial S.R.L., Año" o ": Editorial."
        if texto_ocr:
            m_cip = re.search(r':\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\.]+?),\s*\d{4}', texto_ocr)
            if m_cip:
                ed = m_cip.group(1).strip().rstrip(".")
                if 2 < len(ed) < 40 and not any(k in ed.lower() for k in ["ciudad", "buenos aires", "argentina", "españa"]):
                    return _capitalizar(ed), 92

        # 3. Pattern: © [Año] [Editorial] (descartando si es el autor o el traductor)
        if texto_ocr:
            for m in re.finditer(r"©\s*(19[89]\d|20[0-2]\d)\s*,?\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s\.,]+)", texto_ocr, re.IGNORECASE):
                ed_cand = m.group(2).strip().split("\n")[0].rstrip(",.")
                ed_low = ed_cand.lower()
                if any(k in ed_low for k in ["traducción", "traduccion", "derechos", "arrangement", "literary", "agency", "esta edición"]):
                    continue
                if autor_candidato and any(
                    token in ed_low
                    for token in autor_candidato.lower().split()
                    if len(token) > 3
                ):
                    continue
                if 2 < len(ed_cand) < 40:
                    return _capitalizar(ed_cand), 90

        # 4. Menciones explícitas de sello o editorial
        if texto_ocr:
            m_sello = re.search(
                r"(?:sello|editorial|grupo editorial|publicado por)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+?)(?:®|©|\.|\n|,|$)",
                texto_ocr,
                re.IGNORECASE,
            )
            if m_sello:
                ed = m_sello.group(1).strip()
                if 2 < len(ed) < 40 and not any(k in ed.lower() for k in ["derechos", "harriman"]):
                    return _capitalizar(ed), 88

        # 5. Lista de conocidas en las líneas
        for linea in lineas:
            ll = linea.lower().strip()
            for ed in EDITORIALES_CONOCIDAS:
                if re.search(r"\b" + re.escape(ed) + r"\b", ll):
                    return _capitalizar(ed), 85

        return "", 0

    def _extraer_autor(self, lineas: list[str]) -> tuple[str, int]:
        """Autor — patrón nombre propio en primeras líneas. Rechaza ruido de imprenta."""
        FRAGMENTOS_NO_AUTOR = {
            "argentina", "españa", "spain", "mexico", "colombia", "chile",
            "brazil", "brasil", "peru", "madrid", "barcelona",
            "buenos aires", "avellaneda",
            "printed", "impreso", "hecho", "print",
            "editorial", "editor", "traductor", "traduccion", "traducción",
            "ilustrador", "derechos", "edicion", "edición",
            "habitos atomicos", "hábitos atómicos",
        }

        patron_nombre_propio = re.compile(
            r"^([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:\s+(?:de|del|von|van|de la|le|el)?\s*[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){1,3})$"
        )

        autor_encontrado = ""
        for linea in lineas[:12]:
            if self._es_ruido_ocr(linea):
                continue
            l_low = linea.lower().strip()

            if any(k in l_low for k in FRAGMENTOS_NO_AUTOR):
                continue
            if re.search(r"\d", linea):
                continue
            if re.match(r"^(el |la |los |las |de |del |en |por |para |con )", l_low):
                continue
            if re.search(r"[©®:;@/\\%]", linea):
                continue
            if len(linea.split()) > 5:
                continue

            if patron_nombre_propio.match(linea) and len(linea) < 60:
                if not autor_encontrado or len(linea.split()) >= 2:
                    autor_encontrado = _limpiar_autor(linea)
            elif linea.isupper() and 5 < len(linea) < 40 and len(linea.split()) in (2, 3):
                if not autor_encontrado:
                    autor_encontrado = _limpiar_autor(linea)

        return (autor_encontrado, 85) if autor_encontrado else ("", 0)

    def _es_ruido_ocr(self, s: str) -> bool:
        """Detecta si una línea es ruido OCR, delimitadores de sección, datos de imprenta o texto no bibliográfico."""
        if not s:
            return True
        s_stripped = s.strip()
        s_low = s_stripped.lower()

        # Delimitadores de sección y placeholders de captura
        if "===" in s_stripped or any(
            p in s_low for p in [
                "portada / tapa", "portada", "tapa del libro", "ficha catalográfica",
                "contratapa", "desconocido", "sin título", "sin titulo"
            ]
        ):
            return True

        # Demasiado corto
        if len(s_low) < 3:
            return True

        # Citas textuales (entre comillas)
        if s_low.startswith(("«", '"', "\u201c", "'", "\u2018")) or s_low.endswith(("»", '"', "\u201d", "'", "\u2019")):
            return True

        # Palabras de ruido conocidas (imprenta, legales, etc.)
        if any(p in s_low for p in PALABRAS_RUIDO):
            return True

        # Líneas de imprenta: "Printed in X", "Impreso en X", "Hecho en X"
        if re.match(r"^(printed|impreso|hecho|print)\s+(in|en)\s+", s_low):
            return True

        # Líneas que solo contienen números/letras sueltas cortas
        if re.match(r"^[a-z0-9\s]{1,7}$", s_low, re.IGNORECASE):
            return True

        # Líneas con símbolos típicos de datos editoriales o legales
        if re.search(r"[©®@#|]", s_stripped):
            return True

        # Líneas que comienzan con dígito
        if re.match(r"^\d", s_stripped):
            return True

        # URLs o emails
        if re.search(r"\.(com|org|es|ar|net|io|edu)\b|@", s_low):
            return True

        # Texto en minúscula con más de 6 palabras → probable sinopsis/blurb
        if re.match(r"^[a-záéíóúüñ]", s_stripped) and len(s_stripped.split()) > 6:
            return True

        return False

    def _extraer_titulo(self, lineas: list[str], autor_valor: str) -> tuple[str, int]:
        """Título — busca el título principal filtrando ruido, delimitadores y datos de imprenta."""
        FRAGMENTOS_NO_TITULO = [
            "===", "portada", "tapa", "desconocido", "sin título", "sin titulo",
            "printed", "impreso", "hecho en", "print in",
            "argentina", "españa", "spain", "mexico",
            "reservados", "prohibida", "derechos",
            "editorial", "traducc", "isbn", "ibic", "cdu",
            "queda", "permiso", "licencia",
            "saga", "saga de", "colección", "serie",
        ]
        tokens_autor = [t.lower() for t in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}", autor_valor)]

        def _es_titulo_valido(linea: str) -> bool:
            """Retorna True si la línea puede ser un título de libro."""
            if self._es_ruido_ocr(linea):
                return False
            l_low = linea.lower().strip()
            if any(f in l_low for f in FRAGMENTOS_NO_TITULO):
                return False
            if any(ed in l_low for ed in EDITORIALES_CONOCIDAS):
                return False
            if re.match(r"^[\d\s]+$", linea):
                return False
            if len(linea.split()) > 12:
                return False
            if tokens_autor and any(tok in l_low for tok in tokens_autor):
                return False
            return True

        # 1. Buscar líneas en MAYÚSCULAS consecutivas
        lineas_mayus: list[str] = []
        for l in lineas[:15]:
            if not _es_titulo_valido(l):
                if lineas_mayus:
                    break
                continue
            if len(l) > 60:
                if lineas_mayus:
                    break
                continue
            if l.isupper() and len(l) > 3 and not re.search(r"\d", l):
                lineas_mayus.append(l)
            elif lineas_mayus:
                break

        if lineas_mayus:
            titulo_compuesto = " ".join(lineas_mayus).strip()
            return (titulo_compuesto.title() if len(titulo_compuesto) > 4 else titulo_compuesto), 85

        # 2. Fallback: primeras líneas válidas
        posibles = [l for l in lineas[:10] if _es_titulo_valido(l) and len(l) < 100]
        if posibles:
            return posibles[0], 65

        return "", 0

    # ------------------------------------------------------------------
    # Enriquecimiento con Ollama
    # ------------------------------------------------------------------

    async def enriquecer_con_ollama(
        self,
        texto_ocr: str,
        datos_actuales: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Capa OPCIONAL de IA Generativa Local mediante Ollama.
        Completa de forma silenciosa únicamente campos vacíos o de baja confianza.

        Args:
            texto_ocr: Texto crudo proveniente del OCR.
            datos_actuales: Datos acumulados hasta el momento.

        Returns:
            Datos enriquecidos con IA local si corresponde.
        """
        if datos_actuales is None:
            datos_actuales = {}

        config = self._config.get()

        if not config or config.get("motorIaLocal") != "ollama":
            logger.debug(
                "[AgenteAnalizador-Ollama] Motor de IA Local deshabilitado: %s",
                config.get("motorIaLocal") if config else "N/A",
            )
            return datos_actuales

        if not texto_ocr or not texto_ocr.strip():
            logger.warning("[AgenteAnalizador-Ollama] Texto OCR vacío, omitiendo consulta a Ollama.")
            return datos_actuales

        endpoint: str = (config.get("ollamaEndpoint") or "http://localhost:11434").rstrip("/")
        modelo: str = config.get("ollamaModelo") or "gemma4:e2b"
        resultado: dict[str, Any] = dict(datos_actuales)

        logger.info(
            "[AgenteAnalizador-Ollama] 🚀 Iniciando consulta a Ollama. Endpoint: %s, Modelo: %s, Longitud texto: %d",
            endpoint, modelo, len(texto_ocr),
        )

        prompt = (
            "Eres un asistente bibliotecario experto de alta precisión. Analiza el siguiente texto extraído por OCR de un libro "
            "(que incluye bloques identificados: PORTADA/TAPA, FICHA CATALOGRÁFICA/INTERIOR y CONTRATAPA) "
            "y extrae los campos editoriales estructurados en formato JSON.\n\n"
            "REGLAS ESTRICTAS DE CORRECCIÓN Y EXTRACCIÓN (OBLIGATORIO):\n\n"
            "1. TÍTULO (\"titulo\"):\n"
            "   - NUNCA insertes marcadores de posición, delimitadores de sección ni textos como '=== Portada / Tapa Del Libro ===', 'Portada', 'Desconocido' o 'Sin Título'.\n"
            "   - El título DEBE ser el nombre real de la obra tal como aparece impreso en la tapa o en la portada interior.\n"
            "   - Si el título en la tapa está dividido en múltiples líneas, únelas en una sola frase coherente.\n"
            "   - NUNCA incluyas nombres de sagas, series, universos, subtítulos de colección ni el nombre del autor dentro del título.\n"
            "   - El campo 'titulo' y el campo 'editorial' jamás pueden tener el mismo valor.\n\n"
            "2. SINOPSIS (\"sinopsis\"):\n"
            "   - Analiza siempre el bloque de CONTRATAPA (parte trasera del libro).\n"
            "   - Transcribe ÍNTEGRAMENTE el texto descriptivo, reseña, cita o fragmento promocional que aparece en la contratapa.\n"
            "   - NUNCA lo dejes en \"\" o null si hay texto visible en la contratapa.\n\n"
            "3. AUTOR (\"autor\"):\n"
            "   - Extrae el nombre propio de la persona autora destacada.\n"
            "   - Limpia el formato de los nombres: elimina puntos innecesarios o mayúsculas sostenidas rígidas (ejemplo: convierte mayúsculas a formato de nombre propio limpio).\n"
            "   - NUNCA tomes nombres de traductores, ilustradores, prologuistas o editores.\n\n"
            "4. EDITORIAL (\"editorial\"):\n"
            "   - Da prioridad estricta al sello o editorial de la edición física actual visible en la portada o en la página de legales/derechos de autor.\n"
            "   - En historiales con múltiples ediciones pasadas, selecciona siempre el sello de la edición actual más reciente.\n"
            "   - Extrae solo el nombre limpio de la editorial, omitiendo ciudades, direcciones o códigos postales.\n\n"
            "5. GÉNERO (\"genero\"):\n"
            "   - En lugar de géneros genéricos en inglés como 'Fiction' o 'Juvenile Nonfiction', infiere o extrae una categoría bibliográfica precisa en español según el contexto del libro (ejemplos: 'Literatura Fantástica', 'Narrativa Francesa', 'Finanzas Personales', 'Ciencia Ficción', 'Desarrollo Personal', 'Infantil / Juvenil', etc.).\n\n"
            "6. PORTADA (\"portada\"):\n"
            "   - Cuando se procesa directamente por OCR y no proviene de una API de búsqueda externa, asigna SIEMPRE una cadena vacía \"\" (en lugar de inventar o autogenerar enlaces).\n\n"
            "7. AÑO (\"anio\"), ISBN (\"isbn\"), PÁGINAS (\"paginas\"):\n"
            "   - anio: Año de 4 dígitos de la edición/impresión física más reciente.\n"
            "   - isbn: Número de 10 o 13 dígitos limpio (sin guiones).\n"
            "   - paginas: Número entero de páginas de la obra.\n\n"
            "Devuelve ÚNICAMENTE un objeto JSON válido con las siguientes claves:\n"
            "{\"titulo\": \"...\", \"autor\": \"...\", \"editorial\": \"...\", \"anio\": \"...\", \"isbn\": \"...\", \"paginas\": \"...\", \"genero\": \"...\", \"sinopsis\": \"...\", \"portada\": \"\"}\n\n"
            f"Texto OCR:\n\"\"\"\n{texto_ocr[:3500]}\n\"\"\""
        )

        payload: dict[str, Any] = {
            "model": modelo,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        async def _enviar(target_url: str) -> Optional[httpx.Response]:
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
                    resp = await client.post(
                        f"{target_url}/api/generate",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                return resp
            except Exception as err:
                logger.warning(
                    "[AgenteAnalizador-Ollama] Error de fetch a %s: %s", target_url, err
                )
                return None

        try:
            resp = await _enviar(endpoint)
            if resp is None and "localhost" in endpoint:
                alt_url = endpoint.replace("localhost", "127.0.0.1")
                logger.info("[AgenteAnalizador-Ollama] Reintentando con IP alternativa: %s", alt_url)
                resp = await _enviar(alt_url)

            if resp is None or resp.status_code >= 400:
                logger.warning(
                    "[AgenteAnalizador-Ollama] Conexión o respuesta HTTP no OK desde Ollama (%s)",
                    resp.status_code if resp is not None else "N/A",
                )
                return datos_actuales

            data = resp.json()
            raw_response = data.get("response")
            logger.debug("[AgenteAnalizador-Ollama] Respuesta cruda recibida de Ollama: %s", raw_response)
            if not raw_response:
                return datos_actuales

            parsed: dict[str, Any] = (
                raw_response if isinstance(raw_response, dict) else json.loads(raw_response)
            )
            logger.debug("[AgenteAnalizador-Ollama] JSON parseado con éxito: %s", parsed)

            ed_propuesta = str(parsed.get("editorial") or "").strip().lower()
            aut_propuesto = str(parsed.get("autor") or "").strip().lower()

            def _es_val_ruidoso(campo: str, val: str) -> bool:
                if not val or val in ("a", "—"):
                    return True
                v = val.lower().strip()
                if any(m in v for m in [
                    "===", "portada / tapa", "portada", "tapa del libro",
                    "ficha catalográfica", "contratapa", "desconocido", "sin título", "sin titulo",
                ]):
                    return True
                if campo == "titulo":
                    if ed_propuesta and (v == ed_propuesta or v in ed_propuesta or ed_propuesta in v):
                        return True
                    if aut_propuesto and (v == aut_propuesto or v in aut_propuesto):
                        return True
                    es_direccion = any(k in v for k in [
                        "ciudad", "autón", "buenos aires", "edición", "impreso",
                        "derechos", "www.", "http", "mo mo", "4titul", "na de",
                    ])
                    es_eslogan = (
                        "riqueza no es fruto" in v
                        or "fruto de nuestro" in v
                        or len(val) > 100
                        or (val.count(",") + val.count("|") + val.count("/")) >= 3
                        or len(val) < 2
                    )
                    return es_direccion or es_eslogan
                return False

            campos = ["titulo", "autor", "editorial", "anio", "isbn", "paginas", "genero", "sinopsis"]
            for campo in campos:
                val_ollama: str = str(parsed.get(campo) or "").strip()

                if not val_ollama:
                    continue

                if campo == "titulo" and _es_val_ruidoso("titulo", val_ollama):
                    logger.warning(
                        "[AgenteAnalizador-Ollama] Título de Ollama descartado por ser ruidoso: %s",
                        val_ollama,
                    )
                    continue

                # Limpieza cosmética de autor
                if campo == "autor":
                    val_ollama = _limpiar_autor(val_ollama)

                # Limpieza cosmética de título
                if campo == "titulo":
                    if val_ollama.isupper() and len(val_ollama) > 3:
                        val_ollama = val_ollama.title()

                # Limpieza de ISBN
                if campo == "isbn":
                    val_ollama = re.sub(r"[^0-9X]", "", val_ollama.upper())

                # Normalización de género
                if campo == "genero":
                    val_ollama = _normalizar_genero(val_ollama)

                resultado[campo] = {"valor": val_ollama, "confianza": 90, "fuente": "IA_local"}
                logger.debug(
                    "[AgenteAnalizador-Ollama] Campo \"%s\" establecido por Ollama: \"%s\"",
                    campo, val_ollama,
                )

            # Fallback de sinopsis si Ollama no extrajo o dejó vacío
            sinopsis_val = (resultado.get("sinopsis") or {}).get("valor", "")
            if not sinopsis_val or len(sinopsis_val) < 15:
                sin_fallback, conf_fb = self._extraer_sinopsis(texto_ocr)
                if sin_fallback:
                    resultado["sinopsis"] = {
                        "valor": sin_fallback,
                        "confianza": conf_fb,
                        "fuente": "OCR_Sintetizado",
                    }

        except Exception as err:
            logger.warning(
                "[AgenteAnalizador-Ollama] Error parseando JSON de Ollama (fallback a datos Regex): %s", err
            )

        return resultado

    # ------------------------------------------------------------------
    # Enriquecimiento completo (Ollama + API externa)
    # ------------------------------------------------------------------

    async def enriquecer(
        self,
        isbn: str,
        datos_ocr: Optional[dict[str, Any]] = None,
        texto_crudo: str = "",
    ) -> dict[str, Any]:
        """
        Consulta APIs externas (Google Books / OpenLibrary), aplica la Regla
        de Fuentes y prueba IA Local si persisten vacíos.

        Orden de prioridad:
          1. Enriquecimiento con Ollama (extrae/corrige campos y ISBN).
          2. Enriquecimiento con API externa (validación oficial por ISBN).
          3. Regla contextual de respaldo.
          4. Completar campos faltantes con estado 'pendiente_carga_manual'.

        Args:
            isbn: ISBN detectado por OCR (puede estar vacío).
            datos_ocr: Resultado de procesar_texto_ocr().
            texto_crudo: Texto OCR original completo.

        Returns:
            Diccionario con todos los campos editoriales enriquecidos.
        """
        if datos_ocr is None:
            datos_ocr = {}

        enriquecido: dict[str, Any] = dict(datos_ocr)

        # 1. Enriquecimiento con Ollama
        texto_para_ia = texto_crudo or str(datos_ocr.get("_texto_crudo", "")) or ""
        enriquecido = await self.enriquecer_con_ollama(texto_para_ia, enriquecido)

        # 2. Determinar los mejores candidatos disponibles
        isbn_candidato: str = (enriquecido.get("isbn") or {}).get("valor", "") or isbn or ""
        autor_candidato: str = (enriquecido.get("autor") or {}).get("valor", "") or \
                               (datos_ocr.get("autor") or {}).get("valor", "")
        titulo_candidato: str = (enriquecido.get("titulo") or {}).get("valor", "") or \
                                (datos_ocr.get("titulo") or {}).get("valor", "")

        buscar_fn = self._buscar_por_isbn_fn or self._buscar_por_isbn_api
        if isbn_candidato or autor_candidato or titulo_candidato:
            logger.info(
                "[AgenteAnalizador] Consultando API de Libros con ISBN: %s | Autor: %s | Título: %s",
                isbn_candidato, autor_candidato, titulo_candidato,
            )
            api_data: Optional[dict[str, Any]] = None
            try:
                api_data = await buscar_fn(
                    isbn_candidato, autor_candidato, titulo_candidato
                )
            except Exception as e:
                logger.warning("[AgenteAnalizador] Falla al consultar API de enriquecimiento: %s", e)

            if api_data:
                logger.info("[AgenteAnalizador] Datos oficiales devueltos por API: %s", api_data)
                enriquecido = self._aplicar_reglas_api(enriquecido, api_data, datos_ocr)

        # 3. Completar campos faltantes
        for k in CAMPOS_EDITORIALES:
            if not enriquecido.get(k) or not (enriquecido[k] or {}).get("valor"):
                enriquecido[k] = {"valor": "", "confianza": 0, "estado": "pendiente_carga_manual"}

        return enriquecido

    def _es_ruido_api(self, val: str, autor_candidato: str = "") -> bool:
        """Detecta valores ruidosos en datos de API."""
        if not val:
            return True
        v = val.lower().strip()
        if len(v) < 3:
            return True
        if v[0] in ("—", "-", "~", "|"):
            return True
        if not re.search(r"[a-záéíóúüñ]{3,}", v, re.IGNORECASE):
            return True
        autor_nom = autor_candidato.lower().strip()
        if autor_nom and (v == autor_nom or autor_nom in v or v in autor_nom):
            return True
        if any(p in v for p in PALABRAS_RUIDO):
            return True
        return False

    async def _buscar_por_isbn_api(
        self, isbn: str, autor: str = "", titulo: str = ""
    ) -> Optional[dict[str, Any]]:
        """Busca metadatos oficiales en Google Books API y OpenLibrary."""
        isbn_limpio = re.sub(r"[^0-9X]", "", (isbn or "").upper())
        # 1. Google Books
        if isbn_limpio or titulo:
            q = f"isbn:{isbn_limpio}" if isbn_limpio else f"intitle:{titulo}+inauthor:{autor}"
            url = f"https://www.googleapis.com/books/v1/volumes?q={q}"
            from app.core.config import settings
            if getattr(settings, "GOOGLE_BOOKS_API_KEY", None):
                url += f"&key={settings.GOOGLE_BOOKS_API_KEY}"
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(url, headers={"User-Agent": "BiblioTech/1.0"})
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("totalItems", 0) > 0:
                            v = data["items"][0]["volumeInfo"]
                            return {
                                "isbn": isbn or "",
                                "titulo": v.get("title", ""),
                                "autor": ", ".join(v.get("authors", [])) if v.get("authors") else "",
                                "editorial": v.get("publisher", ""),
                                "anio": str(v.get("publishedDate", ""))[:4] or "",
                                "paginas": str(v.get("pageCount", "")) if v.get("pageCount") else "",
                                "genero": _normalizar_genero(", ".join(v.get("categories", []))) if v.get("categories") else "",
                                "sinopsis": v.get("description", ""),
                                "portada": (v.get("imageLinks") or {}).get("thumbnail", ""),
                            }
            except Exception as err:
                logger.debug("[AgenteAnalizador] Error consultando Google Books: %s", err)

        # 2. OpenLibrary
        if isbn:
            url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(url, headers={"User-Agent": "BiblioTech/1.0"})
                    if resp.status_code == 200:
                        data = resp.json()
                        key = f"ISBN:{isbn}"
                        if key in data:
                            info = data[key]
                            autores = ", ".join(a.get("name", "") for a in info.get("authors", []))
                            pubs = info.get("publishers", [])
                            editorial = pubs[0].get("name", "") if pubs else ""
                            return {
                                "isbn": isbn,
                                "titulo": info.get("title", ""),
                                "autor": autores,
                                "editorial": editorial,
                                "anio": str(info.get("publish_date", ""))[:4] or "",
                                "paginas": str(info.get("number_of_pages", "")) if info.get("number_of_pages") else "",
                                "portada": (info.get("cover") or {}).get("medium", ""),
                            }
            except Exception as err:
                logger.debug("[AgenteAnalizador] Error consultando OpenLibrary: %s", err)

        return None

    def _aplicar_reglas_api(
        self,
        enriquecido: dict[str, Any],
        api_data: dict[str, Any],
        datos_ocr: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica las Reglas de Fuentes sobre los datos de API."""
        autor_candidato: str = (enriquecido.get("autor") or {}).get("valor", "")

        def _es_ruido(v: str) -> bool:
            return self._es_ruido_api(v, autor_candidato)

        # 1. Regla de Validación por ISBN — Título y Autor Oficiales
        titulo_act_conf = (enriquecido.get("titulo") or {}).get("confianza", 0)
        titulo_act_val = (enriquecido.get("titulo") or {}).get("valor", "")
        if api_data.get("titulo") and (_es_ruido(titulo_act_val) or titulo_act_conf <= 75 or not titulo_act_val):
            enriquecido["titulo"] = {"valor": api_data["titulo"], "confianza": 98, "fuente": "API_Oficial"}
            logger.info('[AgenteAnalizador] ✅ Título validado por ISBN desde API Oficial: "%s"', api_data["titulo"])

        autor_act_conf = (enriquecido.get("autor") or {}).get("confianza", 0)
        autor_act_val = (enriquecido.get("autor") or {}).get("valor", "")
        if api_data.get("autor") and (_es_ruido(autor_act_val) or autor_act_conf <= 75 or not autor_act_val):
            autores_raw = [a.strip() for a in api_data["autor"].split(",") if a.strip()]
            autores_filtrados = []
            for a in autores_raw:
                if any(t in a.lower() for t in ["faraldo", "traductor", "translator", "ilustrador", "illustrator"]):
                    continue
                autores_filtrados.append(a)
            autor_final = _limpiar_autor(", ".join(autores_filtrados) if autores_filtrados else api_data["autor"])
            enriquecido["autor"] = {"valor": autor_final, "confianza": 98, "fuente": "API_Oficial"}
            logger.info('[AgenteAnalizador] ✅ Autor validado por ISBN desde API Oficial: "%s"', autor_final)

        # 2. Regla Crítica de Prioridad Física — Año de Edición Local
        anio_act = (enriquecido.get("anio") or {}).get("valor", "")
        if not anio_act and api_data.get("anio"):
            enriquecido["anio"] = {"valor": str(api_data["anio"]), "confianza": 90, "fuente": "API_Oficial"}
        elif anio_act:
            logger.info(
                '[AgenteAnalizador] 🛡️ Preservando Año de Edición Física Local: "%s" (API devolvió: "%s")',
                anio_act, api_data.get("anio"),
            )

        # 3. ISBN Físico Local
        isbn_act = (enriquecido.get("isbn") or {}).get("valor", "")
        if not isbn_act and api_data.get("isbn"):
            enriquecido["isbn"] = {"valor": api_data["isbn"], "confianza": 95, "fuente": "API_Oficial"}
        elif isbn_act:
            logger.info('[AgenteAnalizador] 🛡️ Preservando ISBN Físico Local: "%s"', isbn_act)

        # 3.5 Páginas Físicas Locales
        paginas_act = (enriquecido.get("paginas") or {}).get("valor", "")
        if not paginas_act and api_data.get("paginas"):
            enriquecido["paginas"] = {"valor": str(api_data["paginas"]), "confianza": 85, "fuente": "API_Oficial"}
        elif paginas_act and api_data.get("paginas") and str(paginas_act) != str(api_data["paginas"]):
            logger.info(
                '[AgenteAnalizador] 🛡️ Preservando Páginas de Edición Física Local: "%s" (API devolvió: "%s")',
                paginas_act, api_data["paginas"],
            )

        # 4. Campos complementarios: Sinopsis, Género, Editorial, Portada
        genero_api = _normalizar_genero(api_data.get("genero") or "")
        campos_complementarios: list[tuple[str, Any, int]] = [
            ("sinopsis", api_data.get("sinopsis"), 90),
            ("genero", genero_api, 85),
            ("portada", api_data.get("portada"), 95),
            ("editorial", api_data.get("editorial"), 85),
        ]
        for campo, valor, conf in campos_complementarios:
            act = enriquecido.get(campo) or {}
            act_val = act.get("valor", "")
            # Para portada, solo asignar si la API trajo una URL real
            if campo == "portada" and not valor:
                continue
            if valor and (not act_val or _es_ruido(act_val)):
                enriquecido[campo] = {"valor": valor, "confianza": conf, "fuente": "API_Oficial"}
                logger.debug('[AgenteAnalizador] Campo enriquecido por API: "%s" -> "%s"', campo, valor)

        return enriquecido

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def nivel_confianza(self, pct: int) -> str:
        """
        Categoriza un porcentaje de confianza.

        Returns:
            'high' si pct >= 85, 'mid' si pct >= 65, 'low' de lo contrario.
        """
        if pct >= 85:
            return "high"
        if pct >= 65:
            return "mid"
        return "low"
