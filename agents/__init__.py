"""
BiblioTech — Red de Agentes (agentes/__init__.py)
==================================================
Punto de entrada unificado del package `agentes`.
Análogo a js/agents/index.js, reexporta todos los agentes y el helper de Ollama.

Uso básico:
    from agentes import (
        AgenteCaptura,
        AgenteAnalizador,
        AgenteEvaluador,
        AgentePlanificador,
        AgenteAprendizaje,
        ejecutar_redaccion_ollama,
        RepositorioBibliotech,
    )

    # Construir el contenedor con las implementaciones reales del backend:
    repo = RepositorioBibliotech(
        libros=...,
        lectores=...,
        prestamos=...,
        reservas=...,
        notificaciones=...,
        config=...,
        aprendizaje=...,
        auditoria=...,
    )

    # Instanciar agentes:
    captura     = AgenteCaptura()
    analizador  = AgenteAnalizador(config_repo=repo.config)
    evaluador   = AgenteEvaluador(repo=repo)
    planificador = AgentePlanificador(repo=repo, evaluador=evaluador)
    aprendizaje = AgenteAprendizaje(repo=repo)
"""

from .agente_analizador import AgenteAnalizador
from .agente_aprendizaje import AgenteAprendizaje
from .agente_captura import AgenteCaptura
from .agente_evaluador import AgenteEvaluador
from .agente_planificador import AgentePlanificador
from .ollama_helper import ejecutar_redaccion_ollama
from .repositorios import (
    RepositorioAprendizaje,
    RepositorioAuditoria,
    RepositorioBibliotech,
    RepositorioConfig,
    RepositorioLectores,
    RepositorioLibros,
    RepositorioNotificaciones,
    RepositorioPrestamos,
    RepositorioReservas,
)

__all__ = [
    # Agentes
    "AgenteCaptura",
    "AgenteAnalizador",
    "AgenteEvaluador",
    "AgentePlanificador",
    "AgenteAprendizaje",
    # Helper Ollama
    "ejecutar_redaccion_ollama",
    # Interfaces de repositorio
    "RepositorioBibliotech",
    "RepositorioLibros",
    "RepositorioLectores",
    "RepositorioPrestamos",
    "RepositorioReservas",
    "RepositorioNotificaciones",
    "RepositorioConfig",
    "RepositorioAprendizaje",
    "RepositorioAuditoria",
]
