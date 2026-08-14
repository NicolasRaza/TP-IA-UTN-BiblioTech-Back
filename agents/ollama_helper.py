"""
BiblioTech — Helper de Integración con Ollama (agentes/ollama_helper.py)
========================================================================
Migración de js/agents/ollama-helper.js

Mantiene:
  - Timeout de 45 segundos
  - Fallback de localhost a 127.0.0.1
  - Ante cualquier falla devuelve fallback_texto sin lanzar excepción
  - Motor deshabilitado devuelve fallback_texto directamente
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .repositorios import RepositorioConfig

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS: float = 45.0


async def ejecutar_redaccion_ollama(
    prompt: str,
    fallback_texto: str,
    config_repo: RepositorioConfig,
) -> str:
    """
    Ejecuta una solicitud de redacción en lenguaje natural a la instancia
    local de Ollama.

    Args:
        prompt: Prompt formateado con los datos pre-calculados.
        fallback_texto: Texto por defecto si Ollama está deshabilitado o falla.
        config_repo: Repositorio de configuración inyectado.

    Returns:
        Texto redactado por Ollama o fallback_texto ante cualquier falla.
    """
    config: dict[str, Any] = config_repo.get()

    if not config or config.get("motorIaLocal") != "ollama" or not prompt:
        return fallback_texto

    endpoint: str = (config.get("ollamaEndpoint") or "http://localhost:11434").rstrip("/")
    modelo: str = config.get("ollamaModelo") or "llama3.2"

    payload: dict[str, Any] = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
    }

    async def _enviar(target_url: str) -> Optional[httpx.Response]:
        """Envía el POST a Ollama con timeout de 45s. Devuelve None ante falla."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
                resp = await client.post(
                    f"{target_url}/api/generate",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            return resp
        except Exception as err:
            logger.warning("[RedaccionOllama] Error de conexión a %s: %s", target_url, err)
            return None

    try:
        resp = await _enviar(endpoint)

        # Fallback localhost → 127.0.0.1 (igual que el original JS)
        if resp is None and "localhost" in endpoint:
            alt_url = endpoint.replace("localhost", "127.0.0.1")
            resp = await _enviar(alt_url)

        if resp is None or resp.status_code >= 400:
            logger.warning(
                "[RedaccionOllama] HTTP o conexión fallida al consultar Ollama (status=%s)",
                resp.status_code if resp is not None else "N/A",
            )
            return fallback_texto

        data: dict[str, Any] = resp.json()
        texto_generado: str = (data.get("response") or "").strip()
        return texto_generado or fallback_texto

    except Exception as err:
        logger.warning(
            "[RedaccionOllama] Ollama local inaccesible (fallback activado): %s", err
        )
        return fallback_texto
