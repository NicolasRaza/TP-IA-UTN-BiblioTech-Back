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
  - Regla contextual específica "La psicología del dinero"
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
    "anio", "paginas", "genero", "sinopsis", "portada",
]

EDITORIALES_CONOCIDAS: list[str] = [
    "planeta", "sudamericana", "emecé", "alfaguara", "anagrama", "seix barral",
    "tusquets", "debolsillo", "salamandra", "fondo de cultura", "debate", "crítica",
    "lumen", "alba", "suma", "random house", "siglo xxi", "norma", "paidós", "granica",
    "océano", "vergara", "urano", "siruela", "roca editorial", "ediciones b",
]

PALABRAS_RUIDO: list[str] = [
    "na de", "ool", "mo mo", "cdd", "4titul", "ciudad", "autóno",
    "buenos aires", "derechos", "impreso", "depósito", "ley 11",
    "reproducción", "alquiler", "charlone", "avellaneda", "edición:", "ejemplares",
]


def _capitalizar(s: str) -> str:
    """Equivalente a la función capitalizar() de utils.js."""
    return s.capitalize() if s else s


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
            "paginas":   {"valor": "", "confianza": 0},
            "genero":    {"valor": "", "confianza": 0},
            "sinopsis":  {"valor": "", "confianza": 0},
        }

        # 1. ISBN — Extracción tolerante a errores OCR
        isbn_valor, isbn_confianza = self._extraer_isbn(texto_ocr)
        if isbn_valor:
            logger.debug("[AgenteAnalizador] ISBN detectado: %s (confianza: %d%%)", isbn_valor, isbn_confianza)
            resultado["isbn"] = {"valor": isbn_valor, "confianza": isbn_confianza}

        # 2. Año de Publicación — Jerarquía Temporal de Edición Actual
        anio_valor, anio_confianza = self._extraer_anio(texto_ocr)
        if anio_valor:
            resultado["anio"] = {"valor": anio_valor, "confianza": anio_confianza}

        # 3. Páginas
        paginas_valor, paginas_confianza = self._extraer_paginas(texto_ocr)
        if paginas_valor:
            resultado["paginas"] = {"valor": paginas_valor, "confianza": paginas_confianza}

        # 4. Editorial
        editorial_valor, editorial_confianza = self._extraer_editorial(lineas)
        if editorial_valor:
            resultado["editorial"] = {"valor": editorial_valor, "confianza": editorial_confianza}

        # 5. Autor
        autor_valor, autor_confianza = self._extraer_autor(lineas)
        if autor_valor:
            resultado["autor"] = {"valor": autor_valor, "confianza": autor_confianza}

        # 6. Título (con descarte de ruido OCR)
        titulo_valor, titulo_confianza = self._extraer_titulo(lineas, resultado.get("autor", {}).get("valor", ""))
        if titulo_valor:
            resultado["titulo"] = {"valor": titulo_valor, "confianza": titulo_confianza}

        return resultado

    def _extraer_isbn(self, texto: str) -> tuple[str, int]:
        """ISBN — niveles de confianza decreciente."""
        # Nivel 1: patrón estricto ISBN-13 (978/979 bien reconocido)
        m = re.search(r"\b(?:ISBN[-:\s]*)?(97[89][\d\s\-]{10,17})\b", texto, re.IGNORECASE)
        if m:
            candidato = re.sub(r"[\s\-]", "", m.group(1))
            if len(candidato) == 13:
                return candidato, 95

        # Nivel 2: cualquier secuencia de ~12-13 dígitos
        candidatos = re.findall(r"[\d][\d\s\-]{11,20}[\d]", texto)
        for c in candidatos:
            digits = re.sub(r"[^\d]", "", c)
            if len(digits) < 12 or len(digits) > 13:
                continue
            if len(digits) == 13 and (digits.startswith("978") or digits.startswith("979")):
                return digits, 80
            if len(digits) == 13 and (digits.startswith("078") or digits.startswith("079")):
                return "9" + digits[1:], 65
            if len(digits) == 12 and digits.startswith("78"):
                return "9" + digits, 60

        return "", 0

    def _extraer_anio(self, texto: str) -> tuple[str, int]:
        """Año — Jerarquía Temporal de Edición Actual (misma lógica JS)."""
        # Regla 1: menciones explícitas de edición/impresión local actual
        pat1 = re.search(
            r"(?:edición|reimpresión|impreso|publicad[oa]|tirada)[^\n\d]{0,40}\b(19[89]\d|20[0-2]\d)\b",
            texto, re.IGNORECASE,
        )
        pat2 = re.search(
            r"\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\b(19[89]\d|20[0-2]\d)\b",
            texto, re.IGNORECASE,
        )
        m = pat1 or pat2
        if m:
            anio = m.group(1)
            logger.debug("[AgenteAnalizador] Año detectado por regla de edición actual: %s", anio)
            return anio, 92

        # Reglas 2 & 3: recolectar todos los años 1980-2029, tomar el más reciente
        candidatos: list[dict] = []
        for linea in texto.split("\n"):
            l_low = linea.lower()
            es_remoto = any(k in l_low for k in ["copyright", "©", "originally", "edición original"])
            matches = re.findall(r"\b(19[89]\d|20[0-2]\d)\b", linea)
            for y in matches:
                candidatos.append({"year": int(y), "str": y, "es_remoto": es_remoto})

        preferidos = [c for c in candidatos if not c["es_remoto"]]
        pool = preferidos if preferidos else candidatos

        if pool:
            mas_reciente = max(pool, key=lambda c: c["year"])
            confianza = 85 if preferidos else 60
            logger.debug(
                "[AgenteAnalizador] Año seleccionado por jerarquía temporal: %s", mas_reciente["str"]
            )
            return mas_reciente["str"], confianza

        return "", 0

    def _extraer_paginas(self, texto: str) -> tuple[str, int]:
        """Páginas — etiqueta antes o número antes."""
        m = re.search(r"(?:páginas?|pags?|pp\.?|paginas?)\s*:\s*(\d{1,4})(?:\s*p\b)?", texto, re.IGNORECASE)
        if m:
            return m.group(1), 85
        m = re.search(r"\b(\d{2,4})\s*(?:páginas?|pags?|pp\.?|paginas?|p\b)", texto, re.IGNORECASE)
        if m:
            return m.group(1), 85
        return "", 0

    def _extraer_editorial(self, lineas: list[str]) -> tuple[str, int]:
        """Editorial — lista de conocidas + pattern copyright."""
        for linea in lineas:
            ll = linea.lower()
            for ed in EDITORIALES_CONOCIDAS:
                if ed in ll:
                    return _capitalizar(ed), 82
            # Pattern: © 2024 Editorial SA  o  Publicado por ...
            m = re.search(r"©\s+\d{4}\s+(.+)", linea, re.IGNORECASE) or \
                re.search(r"(?:Publicado|Published)\s+(?:por|by)\s+(.+)", linea, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:50], 72
        return "", 0

    def _extraer_autor(self, lineas: list[str]) -> tuple[str, int]:
        """Autor — patrón nombre propio en primeras 8 líneas."""
        patron_autor = re.compile(
            r"^([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:\s+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){1,3})$"
        )
        autor_encontrado = ""
        for linea in lineas[:8]:
            if patron_autor.match(linea) and not re.search(r"\d", linea) and len(linea) < 60:
                if not autor_encontrado or len(linea.split()) >= 2:
                    autor_encontrado = linea
        return (autor_encontrado, 75) if autor_encontrado else ("", 0)

    def _es_ruido_ocr(self, s: str) -> bool:
        """Detecta si una línea es ruido OCR o datos de imprenta (misma lógica JS)."""
        if not s:
            return True
        s_low = s.lower().strip()
        if len(s_low) < 5:
            return True
        if any(p in s_low for p in PALABRAS_RUIDO):
            return True
        if re.match(r"^[a-z0-9\s]{1,7}$", s_low, re.IGNORECASE):
            return True
        return False

    def _extraer_titulo(self, lineas: list[str], autor_valor: str) -> tuple[str, int]:
        """Título — primeras 8 líneas filtrando ruido y el autor."""
        posibles = [
            l for l in lineas[:8]
            if not self._es_ruido_ocr(l)
            and len(l) < 120
            and not re.match(r"^\d", l)
            and l != autor_valor
        ]
        return (posibles[0], 65) if posibles else ("", 0)

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
            "Analiza el siguiente texto de portada/ficha técnica de un libro extraído por OCR y extrae los campos editoriales principales.\n"
            "Devuelve UNICAMENTE un objeto JSON válido con las siguientes claves:\n"
            "\"titulo\": (string con el TÍTULO PRINCIPAL del libro EN ESPAÑOL. Si el texto incluye subtítulos de la versión original en inglés como 'Wealth, Greed, and Happiness' o 'Originally published as...', NO uses ese título en inglés; deduce o traduce el título principal en español, por ejemplo 'La psicología del dinero'),\n"
            "\"autor\": (string con el autor o autores),\n"
            "\"editorial\": (string con la editorial),\n"
            "\"anio\": (string de 4 dígitos con el AÑO DE LA EDICIÓN FISICA ACTUAL. Reglas estrictas de jerarquía temporal: 1. Prioridad: Busca explícitamente la fecha de la impresión o edición actual en mano (ej. '2ª edición: febrero de 2024', 'impreso en febrero de 2024', '2024'). 2. Descarte: IGNORA AÑOS ANTIGUOS que acompañen a copyright original (ej. '© 2020', 'Originally published in 2020', '1ª edición 2021'). 3. Selección Múltiple: Si hay varios años en la ficha técnica, elige la fecha MÁS RECIENTE vinculada a la tirada/editorial local actual, NO la fecha histórica original),\n"
            "\"isbn\": (string con el ISBN si se detecta, o \"\"),\n"
            "\"paginas\": (string con la cantidad de páginas si se detecta, o \"\"),\n"
            "\"genero\": (string con el género o categoría temática),\n"
            "\"sinopsis\": (string de 2 a 4 oraciones redactando una síntesis descriptiva del libro basada en la contratapa o tus conocimientos sobre la obra. NUNCA la dejes vacía si hay texto descriptivo o si conoces el libro)\n"
            "\n"
            "Si no puedes determinar un campo con certeza, asigna una cadena vacía \"\".\n"
            f"Texto OCR:\n\"\"\"\n{texto_ocr[:1800]}\n\"\"\""
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

            def _es_val_ruidoso(campo: str, val: str) -> bool:
                if not val or val in ("a", "—"):
                    return True
                if campo == "titulo":
                    v = val.lower()
                    es_direccion = any(k in v for k in [
                        "ciudad", "autón", "buenos aires", "edición", "impreso",
                        "derechos", "www.", "http", "mo mo", "4titul", "na de",
                    ])
                    es_eslogan = (
                        "riqueza no es fruto" in v
                        or "fruto de nuestro" in v
                        or len(val) > 100
                        or (val.count(",") + val.count("|") + val.count("/")) >= 3
                        or len(val) < 5
                    )
                    return es_direccion or es_eslogan
                return False

            campos = ["titulo", "autor", "editorial", "anio", "isbn", "paginas", "genero", "sinopsis"]
            for campo in campos:
                val_actual: str = (resultado.get(campo) or {}).get("valor", "")
                conf_actual: int = (resultado.get(campo) or {}).get("confianza", 0)
                val_ollama: str = str(parsed.get(campo) or "").strip()

                if val_ollama and (_es_val_ruidoso(campo, val_actual) or conf_actual <= 65 or not val_actual):
                    if campo == "titulo" and _es_val_ruidoso("titulo", val_ollama):
                        logger.warning(
                            "[AgenteAnalizador-Ollama] Título de Ollama descartado por ser eslogan: %s",
                            val_ollama,
                        )
                        continue
                    resultado[campo] = {"valor": val_ollama, "confianza": 75, "fuente": "IA_local"}
                    logger.debug(
                        "[AgenteAnalizador-Ollama] Campo \"%s\" enriquecido por Ollama: \"%s\"",
                        campo, val_ollama,
                    )

            # Deducción inteligente por contexto (La psicología del dinero)
            ctx_text = " ".join([
                texto_ocr,
                str(parsed.get("genero", "")),
                str(parsed.get("sinopsis", "")),
                str(parsed.get("autor", "")),
                (resultado.get("autor") or {}).get("valor", ""),
            ]).lower()

            titulo_actual = (resultado.get("titulo") or {}).get("valor", "")
            if _es_val_ruidoso("titulo", titulo_actual) or titulo_actual == "El comportamiento del dinero":
                if (
                    "housel" in ctx_text
                    or ("psicolog" in ctx_text and "dinero" in ctx_text)
                    or "9789504985303" in ctx_text
                ):
                    resultado["titulo"] = {"valor": "La psicología del dinero", "confianza": 98, "fuente": "IA_local"}
                    logger.debug(
                        "[AgenteAnalizador-Ollama] Título deducido con precisión por contexto: %s",
                        resultado["titulo"]["valor"],
                    )

            # Normalización de género
            genero_val = (resultado.get("genero") or {}).get("valor", "")
            if genero_val:
                g_low = genero_val.lower()
                if any(k in g_low for k in ["finanza", "econom", "dinero", "invers"]):
                    resultado["genero"]["valor"] = "Finanzas / Economía"
                elif any(k in g_low for k in ["desarrollo", "autoayuda", "superacion", "personal"]):
                    resultado["genero"]["valor"] = "Desarrollo Personal"
                elif "ciencia ficc" in g_low:
                    resultado["genero"]["valor"] = "Ciencia Ficción"
                elif "historia" in g_low or "ensayo" in g_low:
                    resultado["genero"]["valor"] = "Historia / Ensayo"

            # Fallback de sinopsis
            sinopsis_val = (resultado.get("sinopsis") or {}).get("valor", "")
            t_low = (resultado.get("titulo") or {}).get("valor", "").lower()
            a_low = (resultado.get("autor") or {}).get("valor", "").lower()
            if not sinopsis_val or len(sinopsis_val) < 15:
                if "psicología del dinero" in t_low or "housel" in a_low or "housel" in ctx_text:
                    resultado["sinopsis"] = {
                        "valor": (
                            "En 'La psicología del dinero', Morgan Housel explora cómo los hábitos, "
                            "emociones y comportamientos influyen en nuestras decisiones financieras "
                            "más que los números, ofreciendo lecciones clave sobre cómo administrar "
                            "el dinero y construir riqueza personal."
                        ),
                        "confianza": 90,
                        "fuente": "IA_local",
                    }
                    logger.debug(
                        "[AgenteAnalizador-Ollama] Sinopsis generada automáticamente por contexto."
                    )
                elif texto_ocr and len(texto_ocr) > 50:
                    parrafos = [
                        p for p in texto_ocr.split("\n\n")
                        if len(p) > 40 and "ISBN" not in p and "©" not in p and "www." not in p
                    ]
                    if parrafos:
                        sinopsis_limpia = re.sub(r"\s+", " ", " ".join(parrafos)).strip()[:350]
                        resultado["sinopsis"] = {
                            "valor": sinopsis_limpia,
                            "confianza": 75,
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

        Orden de prioridad (mismo que el JS original):
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

        if (isbn_candidato or autor_candidato or titulo_candidato) and self._buscar_por_isbn_fn:
            logger.info(
                "[AgenteAnalizador] Consultando API de Libros con ISBN: %s | Autor: %s | Título: %s",
                isbn_candidato, autor_candidato, titulo_candidato,
            )
            api_data: Optional[dict[str, Any]] = None
            try:
                api_data = await self._buscar_por_isbn_fn(
                    isbn_candidato, autor_candidato, titulo_candidato
                )
            except Exception as e:
                logger.warning("[AgenteAnalizador] Falla al consultar API de enriquecimiento: %s", e)

            if api_data:
                logger.info("[AgenteAnalizador] Datos oficiales devueltos por API: %s", api_data)
                enriquecido = self._aplicar_reglas_api(enriquecido, api_data, datos_ocr)
        elif (isbn_candidato or autor_candidato or titulo_candidato) and not self._buscar_por_isbn_fn:
            logger.warning("[AgenteAnalizador] buscar_por_isbn_fn no disponible — omitiendo API")

        # 3. Regla contextual específica "La psicología del dinero"
        txt_low = texto_para_ia.lower()
        es_libro_psicologia_dinero = (
            "housel" in txt_low
            or "dinero" in txt_low
            or "9789504985303" in txt_low
            or "riqueza no es fruto" in txt_low
        )
        if es_libro_psicologia_dinero:
            titulo_act = (enriquecido.get("titulo") or {}).get("valor", "")
            autor_act = (enriquecido.get("autor") or {}).get("valor", "")
            genero_act = (enriquecido.get("genero") or {}).get("valor", "")
            paginas_act = (enriquecido.get("paginas") or {}).get("valor", "")

            if not titulo_act or "housel" in titulo_act.lower():
                enriquecido["titulo"] = {"valor": "La psicología del dinero", "confianza": 98, "fuente": "Inferencia_Contextual"}
            if not autor_act:
                enriquecido["autor"] = {"valor": "Morgan Housel", "confianza": 98, "fuente": "Inferencia_Contextual"}
            if not genero_act or genero_act == "Otro" or "Finanz" not in genero_act:
                enriquecido["genero"] = {"valor": "Finanzas / Economía", "confianza": 90, "fuente": "Inferencia_Contextual"}
            if not paginas_act:
                enriquecido["paginas"] = {"valor": "256", "confianza": 88, "fuente": "Base_Conocimiento"}

        # 4. Completar campos faltantes
        for k in CAMPOS_EDITORIALES:
            if not enriquecido.get(k) or not (enriquecido[k] or {}).get("valor"):
                enriquecido[k] = {"valor": "", "confianza": 0, "estado": "pendiente_carga_manual"}

        return enriquecido

    def _es_ruido_api(self, val: str, autor_candidato: str = "") -> bool:
        """Detecta valores ruidosos en datos de API (misma lógica JS)."""
        if not val:
            return True
        v = val.lower().strip()
        if len(v) < 5:
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

    def _aplicar_reglas_api(
        self,
        enriquecido: dict[str, Any],
        api_data: dict[str, Any],
        datos_ocr: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica las Reglas de Fuentes del JS original sobre los datos de API."""
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
            enriquecido["autor"] = {"valor": api_data["autor"], "confianza": 98, "fuente": "API_Oficial"}
            logger.info('[AgenteAnalizador] ✅ Autor validado por ISBN desde API Oficial: "%s"', api_data["autor"])

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
        campos_complementarios: list[tuple[str, Any, int]] = [
            ("sinopsis", api_data.get("sinopsis"), 90),
            ("genero", api_data.get("genero"), 85),
            ("portada", api_data.get("portada"), 95),
            ("editorial", api_data.get("editorial"), 85),
        ]
        for campo, valor, conf in campos_complementarios:
            act = enriquecido.get(campo) or {}
            act_val = act.get("valor", "")
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
