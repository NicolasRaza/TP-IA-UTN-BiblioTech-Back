"""
Agente Planificador y de Gestión Operativa (Scheduler + Push Notifications)
Monitorea vencimientos y dispara notificaciones push via Firebase.
Se inicializa junto con la app FastAPI.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.circulacion import Prestamo, EstadoPrestamo, Reserva, EstadoReserva
from app.models.usuario import Lector, Usuario

logger = logging.getLogger(__name__)


class PlannerService:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self._firebase_app = None

    def iniciar(self) -> None:
        """Se llama al arrancar la app FastAPI."""
        self._inicializar_firebase()
        # Verificar vencimientos todos los días a las 8:00 AM
        self.scheduler.add_job(self.verificar_vencimientos, "cron", hour=8, minute=0)
        # Verificar reservas vencidas cada 2 horas
        self.scheduler.add_job(self.verificar_reservas_vencidas, "interval", hours=2)
        try:
            self.scheduler.start()
            logger.info("Agente Planificador (Scheduler) iniciado")
        except Exception as e:
            logger.warning(f"No se pudo iniciar el scheduler: {e}")

    def detener(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Agente Planificador (Scheduler) detenido")

    def _inicializar_firebase(self):
        try:                                    # ← indentado con 4 espacios
            import firebase_admin               # ← indentado con 8 espacios
            from firebase_admin import credentials
            import json
            from app.core.config import settings

            if firebase_admin._apps:
                return

            if settings.FIREBASE_CREDENTIALS_JSON:
                cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)

            elif settings.FIREBASE_CREDENTIALS_PATH:
                cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)

        except Exception as e:
            logger.warning(f"Firebase no inicializado: {e}")

    async def verificar_vencimientos(self) -> None:
        """Revisa préstamos activos y envía recordatorios 3 días y 1 día antes del vencimiento."""
        async with AsyncSessionLocal() as db:
            hoy = date.today()
            for dias_aviso in [3, 1]:
                fecha_objetivo = hoy + timedelta(days=dias_aviso)
                result = await db.execute(
                    select(Prestamo).where(
                        Prestamo.fecha_devolucion_pactada == fecha_objetivo,
                        Prestamo.estado == EstadoPrestamo.ACTIVO,
                    )
                )
                prestamos = result.scalars().all()
                for prestamo in prestamos:
                    await self._notificar_vencimiento(db, prestamo, dias_aviso)

            # Marcar como vencidos los que pasaron la fecha
            result_vencidos = await db.execute(
                select(Prestamo).where(
                    Prestamo.fecha_devolucion_pactada < hoy,
                    Prestamo.estado == EstadoPrestamo.ACTIVO,
                )
            )
            for prestamo in result_vencidos.scalars().all():
                prestamo.estado = EstadoPrestamo.VENCIDO
                await self._notificar_mora(db, prestamo)

            await db.commit()

    async def verificar_reservas_vencidas(self) -> None:
        """Libera reservas cuyo plazo de retiro venció y pasa al siguiente en la cola."""
        async with AsyncSessionLocal() as db:
            ahora = datetime.utcnow()
            result = await db.execute(
                select(Reserva).where(
                    Reserva.estado == EstadoReserva.DISPONIBLE_RETIRO,
                    Reserva.fecha_limite_retiro < ahora,
                )
            )
            for reserva in result.scalars().all():
                reserva.estado = EstadoReserva.VENCIDA
                logger.info(f"Reserva {reserva.id} vencida por no retiro")

            await db.commit()

    async def enviar_push(self, firebase_token: str, titulo: str, cuerpo: str) -> None:
        """Envía notificación push a un dispositivo específico."""
        if not self._firebase_app:
            logger.debug(f"[PUSH simulado] {titulo}: {cuerpo}")
            return
        try:
            from firebase_admin import messaging
            mensaje = messaging.Message(
                notification=messaging.Notification(title=titulo, body=cuerpo),
                token=firebase_token,
            )
            messaging.send(mensaje)
        except Exception as e:
            logger.error(f"Error enviando push: {e}")

    async def _notificar_vencimiento(self, db: AsyncSession, prestamo: Prestamo, dias: int) -> None:
        lector_result = await db.execute(select(Lector).where(Lector.id == prestamo.lector_id))
        lector = lector_result.scalar_one_or_none()
        if not lector or not lector.usuario:
            return
        token = lector.usuario.firebase_token
        if token:
            await self.enviar_push(
                token,
                titulo="Recordatorio de devolución",
                cuerpo=f"Tenés {dias} {'día' if dias == 1 else 'días'} para devolver tu préstamo.",
            )

    async def _notificar_mora(self, db: AsyncSession, prestamo: Prestamo) -> None:
        lector_result = await db.execute(select(Lector).where(Lector.id == prestamo.lector_id))
        lector = lector_result.scalar_one_or_none()
        if not lector or not lector.usuario:
            return
        token = lector.usuario.firebase_token
        if token:
            dias_mora = (date.today() - prestamo.fecha_devolucion_pactada).days
            await self.enviar_push(
                token,
                titulo="Préstamo vencido",
                cuerpo=f"Tu préstamo lleva {dias_mora} días de atraso. Por favor devolvé el material.",
            )


agente_planificador = PlannerService()
