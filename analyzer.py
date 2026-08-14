"""
Agente Analizador y de Enriquecimiento
Estructura el texto crudo del OCR y enriquece con Google Books / OpenLibrary.
"""
import httpx
from app.agents.capture import TextoCrudo
from app.schemas.libro import OCRResultado
from app.core.config import settings


class AgenteAnalizador:

    async def analizar_y_enriquecer(self, texto: TextoCrudo) -> OCRResultado:
        resultado = OCRResultado()

        # Primer paso: estructurar con heurísticas básicas
        resultado = self._estructurar_texto(texto, resultado)

        # Segundo paso: enriquecer por ISBN si se detectó uno
        if texto.isbn_detectado:
            resultado.isbn = texto.isbn_detectado
            resultado.confianza_isbn = 0.9
            enriquecido = await self._buscar_por_isbn(texto.isbn_detectado)
            if enriquecido:
                resultado = self._aplicar_enriquecimiento(resultado, enriquecido)

        return resultado

    def _estructurar_texto(self, texto: TextoCrudo, resultado: OCRResultado) -> OCRResultado:
        """
        Heurísticas básicas de extracción. En producción, esta función
        puede reemplazarse por una llamada a un LLM para mayor precisión.
        """
        lineas_tapa = [l.strip() for l in texto.texto_tapa.splitlines() if l.strip()]
        if lineas_tapa:
            resultado.titulo = lineas_tapa[0]
            resultado.confianza_titulo = 0.6
        if len(lineas_tapa) > 1:
            resultado.autores = lineas_tapa[1]
            resultado.confianza_autores = 0.5

        return resultado

    async def _buscar_por_isbn(self, isbn: str) -> dict | None:
        """Busca en Google Books API y en OpenLibrary como fallback."""
        datos = await self._google_books(isbn)
        if not datos:
            datos = await self._open_library(isbn)
        return datos

    async def _google_books(self, isbn: str) -> dict | None:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        if settings.GOOGLE_BOOKS_API_KEY:
            url += f"&key={settings.GOOGLE_BOOKS_API_KEY}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                data = r.json()
                if data.get("totalItems", 0) > 0:
                    info = data["items"][0]["volumeInfo"]
                    return {
                        "titulo": info.get("title"),
                        "autores": ", ".join(info.get("authors", [])),
                        "editorial": info.get("publisher"),
                        "anio_edicion": str(info.get("publishedDate", ""))[:4] or None,
                        "idioma": info.get("language"),
                        "sinopsis": info.get("description"),
                        "paginas": info.get("pageCount"),
                        "genero": ", ".join(info.get("categories", [])) or None,
                        "portada_url": info.get("imageLinks", {}).get("thumbnail"),
                    }
        except Exception:
            pass
        return None

    async def _open_library(self, isbn: str) -> dict | None:
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                data = r.json()
                key = f"ISBN:{isbn}"
                if key in data:
                    info = data[key]
                    autores = ", ".join(
                        a.get("name", "") for a in info.get("authors", [])
                    )
                    return {
                        "titulo": info.get("title"),
                        "autores": autores or None,
                        "editorial": info.get("publishers", [{}])[0].get("name"),
                        "anio_edicion": str(info.get("publish_date", ""))[:4] or None,
                        "paginas": info.get("number_of_pages"),
                        "portada_url": info.get("cover", {}).get("medium"),
                    }
        except Exception:
            pass
        return None

    def _aplicar_enriquecimiento(self, resultado: OCRResultado, datos: dict) -> OCRResultado:
        """
        Los datos del agente de internet SUGIEREN pero no sobreescriben
        lo que ya confirmó el bibliotecario. Solo se aplican si el campo está vacío.
        """
        if datos.get("titulo") and not resultado.titulo:
            resultado.titulo = datos["titulo"]
            resultado.confianza_titulo = 0.95
        if datos.get("autores") and not resultado.autores:
            resultado.autores = datos["autores"]
            resultado.confianza_autores = 0.95
        resultado.sinopsis = datos.get("sinopsis")
        resultado.genero = datos.get("genero")
        resultado.portada_url = datos.get("portada_url")
        resultado.paginas = datos.get("paginas")
        return resultado


agente_analizador = AgenteAnalizador()
