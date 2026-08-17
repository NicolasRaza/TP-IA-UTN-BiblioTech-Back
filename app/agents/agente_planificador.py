"""
BiblioTech — Agente 4: Planificador y Gestión Operativa (agentes/agente_planificador.py)
=========================================================================================
Migración de js/agents/agente-planificador.js

Reglas de negocio conservadas intactas:
  - Ciclo de orquestación: reservas expiradas → vencimientos → notificaciones proactivas
  - Plazo recordatorio configurable (config.recordatorioAntesDias, default 3)
  - Notificaciones deduplicadas (no se envía si ya existe una del mismo tipo/libro)
  - Textos de notificaciones idénticos al original (en español)
  - Resumen de alertas: vencidos, próximos, reservasVenc

Cambios de plataforma:
  - Acceso a DB via RepositorioBibliotech inyectado por constructor
  - localStorage.setItem eliminado — usa self._repo.reservas directamente
    (el repositorio es el responsable de persistir)
  - Sin window / localStorage
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from .agente_evaluador import AgenteEvaluador
from .repositorios import RepositorioBibliotech

logger = logging.getLogger(__name__)


class AgentePlanificador:
    """
    Agente 4 — Planificador y Gestión Operativa.

    Responsabilidades:
      - Ejecutar el ciclo de orquestación operativa.
      - Procesar reservas expiradas y generar las notificaciones correspondientes.
      - Detectar préstamos vencidos o próximos a vencer y notificar a los lectores.

    Args:
        repo: Contenedor de repositorios BiblioTech inyectado.
        evaluador: Instancia de AgenteEvaluador para delegar decisiones de reservas.
    """

    def __init__(self, repo: RepositorioBibliotech, evaluador: AgenteEvaluador) -> None:
        self._repo = repo
        self._evaluador = evaluador

    # ------------------------------------------------------------------
    # Ciclo principal
    # ------------------------------------------------------------------

    def correr(self) -> list[dict[str, Any]]:
        """
        Ejecuta el ciclo de orquestación operativa.

        Pasos (en orden, idénticos al JS original):
          1. Decisiones de reservas expiradas (delegadas al AgenteEvaluador).
          2. Notificaciones proactivas de préstamos vencidos o próximos a vencer.

        Returns:
            Lista de alertas generadas:
            [
              {'tipo': 'reserva_vencida',  'reserva': Reserva},
              {'tipo': 'vencido',  'libro': Libro, 'lector': Lector, 'prestamo': Prestamo, 'dias': int},
              {'tipo': 'proximo',  'libro': Libro, 'lector': Lector, 'prestamo': Prestamo, 'dias': int},
            ]
        """
        alertas: list[dict[str, Any]] = []
        config = self._repo.config.get() or {}
        hoy = datetime.now(timezone.utc)

        # ── Paso 1: Reservas expiradas ─────────────────────────────────
        decisiones_reservas = self._evaluador.evaluar_reservas_expiradas()
        for d in decisiones_reservas:
            # Actualizar el estado de la reserva a 'vencida' via el repositorio
            self._repo.reservas.cancelar(d["reservaId"])
            # Recuperar la reserva actualizada para el detalle de alerta
            reserva_obj = next(
                (r for r in self._repo.reservas.get_all() if r["id"] == d["reservaId"]),
                {"id": d["reservaId"], "estado": "vencida", **d},
            )
            alertas.append({"tipo": "reserva_vencida", "reserva": reserva_obj})

            # Notificar al lector que perdió la reserva
            self._repo.notificaciones.add({
                "lectorId": d["lectorId"],
                "tipo": "reserva_expirada",
                "titulo": "⌛ Reserva Expirada",
                "descripcion": "Superaste las 48hs para retirar tu libro reservado. La reserva ha sido cancelada.",
                "icono": "⏳",
            })

        # ── Paso 2: Vencimientos de préstamos ─────────────────────────
        prestamos_activos = [
            p for p in self._repo.prestamos.get_all()
            if p.get("estado") in ("activo", "vencido")
        ]
        dias_recordatorio: int = int(config.get("recordatorioAntesDias") or 3)

        for p in prestamos_activos:
            venc = datetime.fromisoformat(
                p["fechaVencimiento"].replace("Z", "+00:00")
            )
            # math.ceil idéntico al JS: diferencia en días exacta
            diff_segundos = (venc - hoy).total_seconds()
            dias_diff = math.ceil(diff_segundos / 86400)

            libro = self._repo.libros.get(p["libroId"])
            lector = self._repo.lectores.get(p["lectorId"])
            if not libro or not lector:
                continue

            if dias_diff < 0:
                # Préstamo ya vencido
                alertas.append({
                    "tipo": "vencido",
                    "libro": libro,
                    "lector": lector,
                    "prestamo": p,
                    "dias": abs(dias_diff),
                })
                # Deduplicación de notificación
                ya_notif = next(
                    (
                        n for n in self._repo.notificaciones.get_by_lector(p["lectorId"])
                        if n.get("tipo") == "prestamo_vencido"
                        and libro["titulo"] in n.get("descripcion", "")
                    ),
                    None,
                )
                if not ya_notif:
                    self._repo.notificaciones.add({
                        "lectorId": p["lectorId"],
                        "tipo": "prestamo_vencido",
                        "titulo": "⚠️ Préstamo vencido",
                        "descripcion": (
                            f'Tu préstamo de "{libro["titulo"]}" venció hace '
                            f'{abs(dias_diff)} {"día" if abs(dias_diff) == 1 else "días"}. '
                            "Por favor devolvelo a la brevedad."
                        ),
                        "icono": "🚨",
                    })

            elif dias_diff <= dias_recordatorio:
                # Próximo a vencer
                alertas.append({
                    "tipo": "proximo",
                    "libro": libro,
                    "lector": lector,
                    "prestamo": p,
                    "dias": dias_diff,
                })
                ya_notif = next(
                    (
                        n for n in self._repo.notificaciones.get_by_lector(p["lectorId"])
                        if n.get("tipo") == "vencimiento_proximo"
                        and libro["titulo"] in n.get("descripcion", "")
                    ),
                    None,
                )
                if not ya_notif:
                    self._repo.notificaciones.add({
                        "lectorId": p["lectorId"],
                        "tipo": "vencimiento_proximo",
                        "titulo": "⏰ Préstamo próximo a vencer",
                        "descripcion": (
                            f'Tu préstamo de "{libro["titulo"]}" vence en '
                            f'{dias_diff} {"día" if dias_diff == 1 else "días"}.'
                        ),
                        "icono": "⏰",
                    })

        return alertas

    # ------------------------------------------------------------------
    # Resumen
    # ------------------------------------------------------------------

    def resumen_alertas(self) -> dict[str, Any]:
        """
        Ejecuta el ciclo y devuelve un resumen numérico de las alertas.

        Returns:
            {
              'vencidos':      int,
              'proximos':      int,
              'reservas_venc': int,
              'detalle':       list[dict],
            }
        """
        alertas = self.correr()
        return {
            "vencidos":      sum(1 for a in alertas if a["tipo"] == "vencido"),
            "proximos":      sum(1 for a in alertas if a["tipo"] == "proximo"),
            "reservas_venc": sum(1 for a in alertas if a["tipo"] == "reserva_vencida"),
            "detalle": alertas,
        }
