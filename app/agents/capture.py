"""
Agente de Captura (OCR + QR)
Procesa las 3 fotos del libro y extrae texto crudo para el Agente Analizador.
"""
import io
import re
from dataclasses import dataclass


@dataclass
class TextoCrudo:
    texto_tapa: str
    texto_ficha: str
    isbn_detectado: str | None


class AgenteCaptura:
    def __init__(self):
        self._tesseract_disponible = False
        try:
            import pytesseract
            self._tesseract_disponible = True
        except ImportError:
            pass

    async def procesar_fotos(self, tapa_bytes: bytes, ficha_bytes: bytes) -> TextoCrudo:
        """
        Extrae texto de las imágenes usando OCR.
        Si Tesseract no está instalado, devuelve texto vacío para fallback manual.
        """
        texto_tapa = ""
        texto_ficha = ""

        if self._tesseract_disponible:
            texto_tapa = self._ocr_imagen(tapa_bytes)
            texto_ficha = self._ocr_imagen(ficha_bytes)
        
        isbn = self._extraer_isbn(texto_ficha) or self._extraer_isbn(texto_tapa)
        return TextoCrudo(
            texto_tapa=texto_tapa,
            texto_ficha=texto_ficha,
            isbn_detectado=isbn,
        )

    def _ocr_imagen(self, imagen_bytes: bytes) -> str:
        try:
            import pytesseract
            from PIL import Image
            imagen = Image.open(io.BytesIO(imagen_bytes))
            return pytesseract.image_to_string(imagen, lang="spa+eng")
        except Exception:
            return ""

    def _extraer_isbn(self, texto: str) -> str | None:
        """Busca patrones ISBN-10 e ISBN-13 en el texto extraído."""
        patrones = [
            r"ISBN[-:\s]*(97[89][-\s]?\d{1,5}[-\s]?\d{1,7}[-\s]?\d{1,6}[-\s]?\d)",
            r"ISBN[-:\s]*(\d{9}[\dX])",
            r"(97[89]\d{10})",
        ]
        for patron in patrones:
            match = re.search(patron, texto, re.IGNORECASE)
            if match:
                isbn = re.sub(r"[-\s]", "", match.group(1))
                return isbn
        return None


agente_captura = AgenteCaptura()
