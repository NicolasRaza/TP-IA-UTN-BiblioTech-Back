"""
BiblioTech — Agente 1: Captura de Información (agentes/agente_captura.py)
=========================================================================
Migración de js/agents/agente-captura.js

Cambios de plataforma:
  - Tesseract.js  →  pytesseract (idiomas spa+eng)
  - File/Blob     →  bytes | str | pathlib.Path
  - Sin dependencias de window / localStorage

Reglas conservadas:
  - Misma regex de detección de ISBN
  - Mismo shape de retorno: texto_crudo, confianza_ocr, isbn_detectado, timestamp
  - Mismo lógica de decodificación QR (prefijos BTL-, BT-, LEC-, EJ-)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Tipo de entrada aceptado por procesarImagenOCR
ImagenInput = Union[bytes, str, Path]

# Shape de retorno de procesarImagenOCR (mismo que JS)
ResultadoOCR = dict  # {texto_crudo: str, confianza_ocr: int, isbn_detectado: str|None, timestamp: str}

# Shape de retorno de decodificarQR (mismo que JS)
ResultadoQR = dict   # {tipo: str, id: str, es_valido: bool}

# Regex de ISBN (idéntica al original JS, adaptada a Python)
_ISBN_REGEX = re.compile(
    r"\b(?:ISBN[-:\s]*)?(97[89][\d\s\-]{10,}|\d{9}[\dX])\b",
    re.IGNORECASE,
)


class AgenteCaptura:
    """
    Agente 1 — Captura de Información.

    Responsabilidades:
      - Ejecutar OCR sobre imágenes usando pytesseract (spa+eng).
      - Extraer el ISBN del texto crudo con regex.
      - Decodificar y validar códigos QR de la biblioteca.

    No requiere inyección de repositorio (no accede a DB).
    """

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    async def procesar_imagen_ocr(self, imagen_or_data: ImagenInput) -> ResultadoOCR:
        """
        Ejecuta pytesseract OCR sobre una imagen o procesa texto crudo.

        Args:
            imagen_or_data: Puede ser:
              - bytes    → imagen en memoria (PNG/JPEG/etc.)
              - Path     → ruta a archivo de imagen
              - str      → texto crudo ya extraído (sin OCR)

        Returns:
            {
              'texto_crudo':     str,
              'confianza_ocr':   int,   # 0-100
              'isbn_detectado':  str | None,
              'timestamp':       str,   # ISO-8601 UTC
            }
        """
        texto_crudo: str = ""
        confianza_ocr: int = 0

        if isinstance(imagen_or_data, (bytes, Path)):
            texto_crudo, confianza_ocr = await self._ejecutar_ocr(imagen_or_data)
        elif isinstance(imagen_or_data, str):
            # Texto crudo ya disponible — sin OCR
            texto_crudo = imagen_or_data
            confianza_ocr = 80

        # Detección de ISBN (misma regex del JS original)
        isbn_match = _ISBN_REGEX.search(texto_crudo)
        isbn_detectado: Optional[str] = None
        if isbn_match:
            # group(1) captura el número sin el prefijo "ISBN:"
            isbn_detectado = re.sub(r"[\s\-]", "", isbn_match.group(1))

        return {
            "texto_crudo": texto_crudo,
            "confianza_ocr": confianza_ocr,
            "isbn_detectado": isbn_detectado,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _ejecutar_ocr(self, fuente: Union[bytes, Path]) -> tuple[str, int]:
        """
        Invoca pytesseract con idiomas spa+eng.
        Devuelve (texto, confianza). Ante error hace fallback a ('', 50).
        """
        try:
            import pytesseract
            from PIL import Image
            import io

            if isinstance(fuente, bytes):
                image = Image.open(io.BytesIO(fuente))
            else:
                image = Image.open(fuente)

            # Obtener datos detallados para calcular confianza promedio
            data = pytesseract.image_to_data(
                image,
                lang="spa+eng",
                output_type=pytesseract.Output.DICT,
            )

            texto = pytesseract.image_to_string(image, lang="spa+eng")

            # Confianza promedio excluyendo valores -1 (espacios/separadores)
            confs = [int(c) for c in data["conf"] if int(c) >= 0]
            confianza = round(sum(confs) / len(confs)) if confs else 75

            return texto, confianza

        except Exception as err:
            logger.warning(
                "[AgenteCaptura] pytesseract error, fallback a texto vacío: %s", err
            )
            return "", 50

    # ------------------------------------------------------------------
    # QR
    # ------------------------------------------------------------------

    def decodificar_qr(self, codigo_qr: str) -> ResultadoQR:
        """
        Decodifica y valida la estructura de códigos QR escaneados.

        Prefijos reconocidos (idénticos al sistema JavaScript):
          - BTL-...  o  LEC-... → tipo 'lector'
          - BT-...   o  EJ-...  → tipo 'ejemplar'

        Args:
            codigo_qr: Cadena cruda del QR escaneado.

        Returns:
            {
              'tipo':     'ejemplar' | 'lector' | 'desconocido',
              'id':       str,
              'es_valido': bool,
            }
        """
        if not codigo_qr or not isinstance(codigo_qr, str):
            return {"tipo": "desconocido", "id": "", "es_valido": False}

        clean: str = codigo_qr.strip()
        upper: str = clean.upper()

        # Lectores: BTL-... o LEC-...
        if upper.startswith("BTL-") or upper.startswith("LEC-"):
            return {"tipo": "lector", "id": clean, "es_valido": True}

        # Ejemplares: BT-... o EJ-...
        if upper.startswith("BT-") or upper.startswith("EJ-"):
            return {"tipo": "ejemplar", "id": clean, "es_valido": True}

        return {"tipo": "desconocido", "id": clean, "es_valido": False}
