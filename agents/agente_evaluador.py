"""
BiblioTech — Agente 3: Evaluador y Motor de Reglas (agentes/agente_evaluador.py)
==================================================================================
Migración de js/agents/agente-evaluador.js

Reglas de negocio conservadas intactas:
  - Evaluación de elegibilidad: activo, sin multas, sin vencidos, límite por categoría
  - Límite institucional = limiteSimultaneo * 2
  - Plazo máximo de retiro de reserva: 48 horas
  - Cálculo de indicadores: top 5 libros, top 5 lectores, top 6 géneros
  - Generación de resumen con Ollama (prompt en español, fallback puro texto)

Cambios de plataforma:
  - Acceso a DB via RepositorioBibliotech inyectado por constructor
  - Sin window / localStorage
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .ollama_helper import ejecutar_redaccion_ollama
from .repositorios import RepositorioBibliotech

logger = logging.getLogger(__name__)


class AgenteEvaluador:
    """
    Agente 3 — Evaluador y Motor de Reglas.

    Responsabilidades:
      - Evaluar elegibilidad de lectores para préstamos.
      - Detectar reservas expiradas (> 48hs en estado 'lista').
      - Calcular indicadores consolidados de uso e inventario.
      - Generar resúmenes ejecutivos con IA local (Ollama) o texto plano.

    Args:
        repo: Contenedor de repositorios BiblioTech inyectado.
    """

    def __init__(self, repo: RepositorioBibliotech) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Elegibilidad
    # ------------------------------------------------------------------

    def evaluar_elegibilidad_lector(self, lector_id: str) -> dict[str, Any]:
        """
        Evalúa si un lector está habilitado para solicitar o reservar un libro.

        Reglas (en orden, mismas que el JS):
          1. El lector debe existir y estar activo.
          2. Sin multas pendientes.
          3. Sin préstamos con fecha de vencimiento superada.
          4. No alcanzó el límite de préstamos simultáneos por categoría
             (institucional = limiteSimultaneo × 2).

        Args:
            lector_id: ID del lector a evaluar.

        Returns:
            {'aprobado': bool, 'motivo': str | None}
        """
        lector = self._repo.lectores.get(lector_id)
        if not lector:
            return {"aprobado": False, "motivo": "Lector no registrado"}
        if not lector.get("activo"):
            return {"aprobado": False, "motivo": "Cuenta de lector inactiva"}

        if lector.get("multasPendientes", 0) > 0:
            return {
                "aprobado": False,
                "motivo": f"Posee multas pendientes por ${lector['multasPendientes']}",
            }

        ahora = datetime.now(timezone.utc)
        prestamos_lector = self._repo.prestamos.get_by_lector(lector_id)

        prestamos_vencidos = [
            p for p in prestamos_lector
            if p.get("estado") in ("activo", "vencido")
            and datetime.fromisoformat(p["fechaVencimiento"].replace("Z", "+00:00")) < ahora
        ]
        if prestamos_vencidos:
            return {"aprobado": False, "motivo": "Tiene préstamos con fecha de devolución vencida"}

        config = self._repo.config.get()
        prestamos_activos = [
            p for p in prestamos_lector
            if p.get("estado") in ("activo", "vencido")
        ]
        limite_base: int = config.get("limiteSimultaneo") or 3
        limite_max: int = limite_base * 2 if lector.get("categoria") == "institucional" else limite_base

        if len(prestamos_activos) >= limite_max:
            return {
                "aprobado": False,
                "motivo": f"Alcanzó el límite máximo de {limite_max} préstamos simultáneos",
            }

        return {"aprobado": True}

    # ------------------------------------------------------------------
    # Reservas expiradas
    # ------------------------------------------------------------------

    def evaluar_reservas_expiradas(self) -> list[dict[str, Any]]:
        """
        Evalúa reservas en estado 'lista' que superaron las 48hs de plazo.

        Returns:
            Lista de decisiones de liberación:
            [{accion, reservaId, libroId, lectorId, motivo}]
        """
        reservas_listas = [
            r for r in self._repo.reservas.get_all()
            if r.get("estado") == "lista"
        ]
        decisiones: list[dict[str, Any]] = []
        hoy = datetime.now(timezone.utc)

        for r in reservas_listas:
            fecha_venc_str = r.get("fechaVencimientoRetiro")
            if fecha_venc_str:
                fecha_venc = datetime.fromisoformat(
                    fecha_venc_str.replace("Z", "+00:00")
                )
                if fecha_venc < hoy:
                    decisiones.append({
                        "accion": "liberar_reserva",
                        "reservaId": r["id"],
                        "libroId": r["libroId"],
                        "lectorId": r["lectorId"],
                        "motivo": "Plazo máximo de retiro (48hs) superado",
                    })

        return decisiones

    # ------------------------------------------------------------------
    # Indicadores
    # ------------------------------------------------------------------

    def calcular_indicadores(self) -> dict[str, Any]:
        """
        Genera indicadores consolidados de uso e inventario.

        Returns:
            {
              'topLibros':   [{libro: Libro, prestamos: int}]  # top 5
              'topLectores': [{lector: Lector, prestamos: int}]  # top 5
              'topGeneros':  [(genero: str, count: int)]  # top 6
            }
        """
        prestamos = self._repo.prestamos.get_all()

        # Top libros
        por_libro: dict[str, int] = {}
        for p in prestamos:
            por_libro[p["libroId"]] = por_libro.get(p["libroId"], 0) + 1
        top_libros = sorted(por_libro.items(), key=lambda x: -x[1])[:5]
        top_libros_objs = [
            {"libro": self._repo.libros.get(lid), "prestamos": n}
            for lid, n in top_libros
            if self._repo.libros.get(lid)
        ]

        # Top lectores
        por_lector: dict[str, int] = {}
        for p in prestamos:
            por_lector[p["lectorId"]] = por_lector.get(p["lectorId"], 0) + 1
        top_lectores = sorted(por_lector.items(), key=lambda x: -x[1])[:5]
        top_lectores_objs = [
            {"lector": self._repo.lectores.get(lid), "prestamos": n}
            for lid, n in top_lectores
            if self._repo.lectores.get(lid)
        ]

        # Top géneros
        por_genero: dict[str, int] = {}
        for p in prestamos:
            libro = self._repo.libros.get(p["libroId"])
            if libro and libro.get("genero"):
                g = libro["genero"]
                por_genero[g] = por_genero.get(g, 0) + 1
        top_generos = sorted(por_genero.items(), key=lambda x: -x[1])[:6]

        return {
            "topLibros": top_libros_objs,
            "topLectores": top_lectores_objs,
            "topGeneros": top_generos,
        }

    # ------------------------------------------------------------------
    # Resumen con IA
    # ------------------------------------------------------------------

    async def generar_resumen_con_ia(
        self, indicadores: Optional[dict[str, Any]] = None
    ) -> str:
        """
        Genera una síntesis ejecutiva en lenguaje natural utilizando Ollama
        de forma opcional.

        Args:
            indicadores: Indicadores previamente calculados por
                         calcular_indicadores(). Si es None, los calcula.

        Returns:
            Texto con el resumen (Ollama o fallback puro).
        """
        ind = indicadores or self.calcular_indicadores()

        str_libros = (
            ", ".join(
                f'"{x["libro"].get("titulo")}" ({x["prestamos"]} préstamos)'
                for x in ind["topLibros"]
            )
            or "Sin préstamos"
        )
        str_generos = (
            ", ".join(f"{g[0]} ({g[1]})" for g in ind["topGeneros"])
            or "Sin datos"
        )
        str_lectores = (
            ", ".join(
                f'{l["lector"].get("nombre")} {l["lector"].get("apellido")}'
                for l in ind["topLectores"]
            )
            or "Sin datos"
        )

        fallback_texto = (
            f"Resumen operativo: Los géneros más solicitados son {str_generos}. "
            f"Los títulos con mayor rotación en inventario incluyen {str_libros}. "
            f"Lectores con mayor actividad registrado: {str_lectores}."
        )

        prompt = (
            "Actúa como el Agente Evaluador de la biblioteca. Redacta un resumen ejecutivo "
            "en español (máximo 3-4 oraciones) para el panel del bibliotecario interpretando "
            "las siguientes estadísticas consolidadas. NO inventes cifras, títulos ni nombres "
            "que no estén en la lista:\n"
            f"- Libros más solicitados: {str_libros}\n"
            f"- Géneros de mayor preferencia: {str_generos}\n"
            f"- Lectores destacados por actividad: {str_lectores}"
        )

        return await ejecutar_redaccion_ollama(prompt, fallback_texto, self._repo.config)
