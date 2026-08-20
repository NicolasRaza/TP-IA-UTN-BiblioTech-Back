"""
BiblioTech — Agente 5: Recomendación y Aprendizaje (agentes/agente_aprendizaje.py)
====================================================================================
Migración de js/agents/agente-aprendizaje.js

Reglas de negocio conservadas intactas:
  - Regla de Ponderación: Cold Start (≤5 préstamos → 100% popularidad)
  - Cold Start: peso_historial = 0.0, peso_popularidad = 1.0
  - Normal:     peso_historial = 0.70, peso_popularidad = 0.30
  - Score historial: +50 mismo autor, +35 mismo género, +30 género de interés
  - Score popularidad: totalPrestamosGlobales × 20, máximo 100
  - Bonus disponible: +15 si hay ejemplar disponible
  - Recomendaciones: top 8, excluyendo ya prestados/reservados
  - Análisis correcciones OCR: mejora estimada = min(correcciones × 2, 40)
  - Análisis recomendaciones: clics tipo 'reserva' → top 3 efectivos
  - Reporte con Ollama (prompt en español, fallback puro texto)

Cambios de plataforma:
  - Acceso a DB via RepositorioBibliotech inyectado por constructor
  - Sin window / localStorage
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .ollama_helper import ejecutar_redaccion_ollama
from .repositorios import RepositorioBibliotech

logger = logging.getLogger(__name__)

# Regla de Ponderación — umbrales y pesos (no modificar sin validar con el negocio)
UMBRAL_COLD_START: int = 5       # ≤ 5 préstamos = cold start
PESO_HISTORIAL_NORMAL: float = 0.70
PESO_POPULARIDAD_NORMAL: float = 0.30
PESO_HISTORIAL_COLD: float = 0.0
PESO_POPULARIDAD_COLD: float = 1.0
SCORE_MISMO_AUTOR: int = 50
SCORE_MISMO_GENERO: int = 35
SCORE_GENERO_INTERES: int = 30
SCORE_POP_POR_PRESTAMO: int = 20
SCORE_POP_MAX: int = 100
BONUS_DISPONIBLE: int = 15
TOP_RECOMENDACIONES: int = 8
TOP_EFECTIVOS: int = 3


class AgenteAprendizaje:
    """
    Agente 5 — Recomendación y Aprendizaje.

    Responsabilidades:
      - Generar recomendaciones personalizadas por la Regla de Ponderación.
      - Analizar correcciones OCR del bibliotecario.
      - Analizar efectividad de recomendaciones anteriores.
      - Generar reporte de evolución con IA local (Ollama) o texto plano.

    Args:
        repo: Contenedor de repositorios BiblioTech inyectado.
    """

    def __init__(self, repo: RepositorioBibliotech) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Recomendaciones
    # ------------------------------------------------------------------

    async def recomendar_para_lector(self, lector_id: str) -> list[dict[str, Any]]:
        """
        Genera recomendaciones personalizadas aplicando la Regla de Ponderación.

        Cold Start (≤ 5 préstamos históricos):
          - 100% popularidad global, 0% historial personal.
        Normal (> 5 préstamos):
          - 70% historial personal, 30% popularidad global.

        Excluye libros ya prestados o reservados por el lector.

        Args:
            lector_id: ID del lector.

        Returns:
            Lista de hasta 8 objetos Libro ordenados por score descendente.
        """
        lector = await self._repo.lectores.get(lector_id)
        if not lector:
            return []

        prestamos = await self._repo.prestamos.get_by_lector(lector_id)
        reservas = await self._repo.reservas.get_by_lector(lector_id)

        ids_prestados = {p["libroId"] for p in prestamos}
        ids_reservados = {r["libroId"] for r in reservas}
        excluir = ids_prestados | ids_reservados

        libros_por_id = [await self._repo.libros.get(lid) for lid in ids_prestados]
        libros_leidos = [l for l in libros_por_id if l]
        cantidad_prestamos_registrados = len(libros_leidos)

        todos_libros = await self._repo.libros.get_all()
        todos = [
            l for l in todos_libros
            if l.get("validado") and l["id"] not in excluir
        ]
        generos_interes: list[str] = lector.get("generosInteres") or []

        # Regla de Ponderación
        es_cold_start = cantidad_prestamos_registrados <= UMBRAL_COLD_START
        peso_historial = PESO_HISTORIAL_COLD if es_cold_start else PESO_HISTORIAL_NORMAL
        peso_popularidad = PESO_POPULARIDAD_COLD if es_cold_start else PESO_POPULARIDAD_NORMAL

        autores_leidos = {
            (l.get("autor") or "").lower()
            for l in libros_leidos
            if l.get("autor")
        }
        generos_leidos = {
            l.get("genero")
            for l in libros_leidos
            if l.get("genero")
        }

        todos_prestamos = await self._repo.prestamos.get_all()

        scored: list[dict[str, Any]] = []
        for libro in todos:
            score_historial: float = 0.0
            score_popularidad: float = 0.0

            a_low = (libro.get("autor") or "").lower()
            if a_low in autores_leidos:
                score_historial += SCORE_MISMO_AUTOR
            if libro.get("genero") in generos_leidos:
                score_historial += SCORE_MISMO_GENERO
            if libro.get("genero") in generos_interes:
                score_historial += SCORE_GENERO_INTERES

            total_prestamos_globales = sum(
                1 for p in todos_prestamos if p["libroId"] == libro["id"]
            )
            score_popularidad = min(total_prestamos_globales * SCORE_POP_POR_PRESTAMO, SCORE_POP_MAX)

            disponible = any(
                e.get("estado") == "disponible"
                for e in (libro.get("ejemplares") or [])
            )
            bonus_disponible = BONUS_DISPONIBLE if disponible else 0

            score_final = (
                score_historial * peso_historial
                + score_popularidad * peso_popularidad
                + bonus_disponible
            )

            scored.append({"libro": libro, "score": score_final, "es_cold_start": es_cold_start})

        scored.sort(key=lambda x: -x["score"])
        return [x["libro"] for x in scored[:TOP_RECOMENDACIONES]]

    # ------------------------------------------------------------------
    # Análisis de correcciones OCR
    # ------------------------------------------------------------------

    async def analizar_correcciones_ocr(self) -> dict[str, Any]:
        """
        Analiza el historial de correcciones hechas por el bibliotecario sobre OCR.

        Returns:
            {
              'patronesDetectados': [{campo: str, correcciones: int, sugerencia: str}],
              'mejora':             int,   # estimada: min(n×2, 40)
              'totalCorrecciones':  int,
            }
        """
        data = self._repo.aprendizaje.get() or {}
        correcciones = data.get("correcciones") or []

        if not correcciones:
            return {"patronesDetectados": [], "mejora": 0, "totalCorrecciones": 0}

        por_campo: dict[str, int] = {}
        for c in correcciones:
            por_campo[c["campo"]] = por_campo.get(c["campo"], 0) + 1

        patrones_detectados = [
            {
                "campo": campo,
                "correcciones": n,
                "sugerencia": (
                    f'El campo "{campo}" presenta un alto índice de ajuste manual. '
                    "Ajustar patrones heurísticos."
                ),
            }
            for campo, n in sorted(por_campo.items(), key=lambda x: -x[1])
        ]

        mejora = min(len(correcciones) * 2, 40)
        return {
            "patronesDetectados": patrones_detectados,
            "mejora": mejora,
            "totalCorrecciones": len(correcciones),
        }

    # ------------------------------------------------------------------
    # Análisis de efectividad de recomendaciones
    # ------------------------------------------------------------------

    async def analizar_recomendaciones(self) -> dict[str, Any]:
        """
        Analiza clics sobre recomendaciones para detectar cuáles derivaron en reserva.

        Returns:
            {
              'masEfectivos': [{libro: Libro, conversiones: int}]  # top 3
              'totalClics':   int,
            }
        """
        data = self._repo.aprendizaje.get() or {}
        clics = data.get("clics") or []

        por_libro: dict[str, int] = {}
        for c in clics:
            if c.get("tipo") == "reserva":
                lid = c["libroId"]
                por_libro[lid] = por_libro.get(lid, 0) + 1

        mas_efectivos = sorted(por_libro.items(), key=lambda x: -x[1])[:TOP_EFECTIVOS]
        mas_efectivos_objs = []
        for lid, n in mas_efectivos:
            lib = await self._repo.libros.get(lid)
            if lib:
                mas_efectivos_objs.append({"libro": lib, "conversiones": n})

        return {"masEfectivos": mas_efectivos_objs, "totalClics": len(clics)}

    # ------------------------------------------------------------------
    # Reporte
    # ------------------------------------------------------------------

    async def generar_reporte(self) -> dict[str, Any]:
        """
        Genera el reporte de aprendizaje y feedback continuo.

        Returns:
            {
              'ocr':     resultado de analizar_correcciones_ocr(),
              'reco':    resultado de analizar_recomendaciones(),
              'resumen': str  (Ollama o fallback),
            }
        """
        ocr = await self.analizar_correcciones_ocr()
        reco = await self.analizar_recomendaciones()

        fallback_resumen = (
            f"Red de Agentes operando con {ocr.get('totalCorrecciones', 0)} correcciones registradas. "
            f"Tasa de precisión OCR optimizada en +{ocr.get('mejora', 0)}%."
        )

        str_patrones = (
            ", ".join(
                f'{p["campo"]} ({p["correcciones"]})'
                for p in ocr.get("patronesDetectados", [])
            )
            or "Ninguno"
        )

        prompt = (
            "Actúa como el Agente de Aprendizaje de la biblioteca. Redacta una oración sintetizada "
            "e informativa en español (máximo 2 oraciones) para el reporte de evolución del sistema. "
            f"NO inventes cifras:\n"
            f"- Correcciones OCR registradas: {ocr.get('totalCorrecciones', 0)}\n"
            f"- Incremento de precisión estimado: +{ocr.get('mejora', 0)}%\n"
            f"- Campos con más correcciones: {str_patrones}"
        )

        resumen = await ejecutar_redaccion_ollama(prompt, fallback_resumen, self._repo.config)

        return {"ocr": ocr, "reco": reco, "resumen": resumen}
