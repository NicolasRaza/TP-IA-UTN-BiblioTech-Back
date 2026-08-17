"""
Agentes BiblioTech — punto de entrada unificado.

Los agentes (captura, analizador, evaluador, planificador, aprendizaje)
fueron desarrollados por el equipo e integrados aquí con sus implementaciones
concretas de repositorio contra PostgreSQL.
"""
from .agente_captura import AgenteCaptura
from .agente_analizador import AgenteAnalizador
from .agente_evaluador import AgenteEvaluador
from .agente_planificador import AgentePlanificador
from .agente_aprendizaje import AgenteAprendizaje
from .repositorios_impl import construir_repositorio

__all__ = [
    "AgenteCaptura",
    "AgenteAnalizador",
    "AgenteEvaluador",
    "AgentePlanificador",
    "AgenteAprendizaje",
    "construir_repositorio",
]
