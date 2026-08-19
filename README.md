# BiblioTech — Backend (SGB API)

Trabajo Final · Inteligencia Artificial Aplicada a Organizaciones · UTN-FRBA

## Qué es

API REST que sirve al Sistema de Gestión de Bibliotecas (SGB): catálogo, circulación (préstamos, reservas, multas), padrón de lectores y cinco agentes de IA que automatizan la carga operativa (captura por OCR, enriquecimiento bibliográfico, planificación de reservas, evaluación de indicadores y aprendizaje continuo). El backend sigue el ciclo de orquestación cíclica definido en el diseño conceptual del proyecto: Observación → Análisis → Decisión → Acción, con el Agente Evaluador decidiendo y el Agente Planificador ejecutando, separados por diseño.

## Enlaces del proyecto

| Recurso | Link |
|---|---|
| **API en producción** | https://tp-ia-utn-bibliotech-back-production.up.railway.app/ |
| **Documentación interactiva (Swagger)** | https://tp-ia-utn-bibliotech-back-production.up.railway.app/docs |
| **Repositorio frontend** | https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Front |
| **Aplicación web (producción)** | https://nicolasraza.github.io/TP-IA-UTN-BiblioTech-Front/ |

## Cómo probarlo

**Health check**, sin autenticación:
```bash
curl https://tp-ia-utn-bibliotech-back-production.up.railway.app/
# {"status":"ok","sistema":"SGB v1.0"}
```

**Login** de administrador, para obtener un JWT y probar el resto de los endpoints:
```bash
curl -X POST https://tp-ia-utn-bibliotech-back-production.up.railway.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@biblioteca.com", "password": "admin123"}'
```

Para explorar todos los endpoints con ejemplos reales, importar la colección de Postman incluida en el repositorio de documentación, o abrir el Swagger de arriba.

## Arquitectura

```
app/
├── api/v1/endpoints/    # auth, lectores, catalogo, circulacion, usuarios, dashboard
├── agents/              # los 5 agentes + adaptadores contra la base real
├── core/                # config, seguridad (JWT/hashing), dependencias
├── db/                  # engine async de SQLAlchemy
├── models/               # 7 entidades: Usuario, Lector, Titulo, Ejemplar, Prestamo, Reserva, Multa
└── schemas/              # validación Pydantic de entrada/salida
```

**Agentes:**

| Agente | Responsabilidad |
|---|---|
| Captura | OCR de las 3 fotos del ejemplar (tapa, contratapa, ficha técnica) |
| Analizador | Estructura los campos y enriquece la ficha por ISBN |
| Planificador | Gestiona la cola de reservas y agenda las notificaciones push (Firebase) |
| Evaluador | Interpreta indicadores operativos y decide la próxima acción, en lenguaje natural |
| Aprendizaje | Ajusta las recomendaciones (70% historial del lector / 30% popularidad general) |

El modelo de datos completo, con las relaciones y multiplicidades, está documentado en el informe final del proyecto (diagrama entidad-relación y diagrama de clases UML).

## Stack tecnológico

- **Framework:** FastAPI + Pydantic (documentación automática vía OpenAPI/Swagger)
- **Base de datos:** PostgreSQL, acceso async con SQLAlchemy 2.0 (`asyncpg`)
- **Autenticación:** JWT (`python-jose`), hashing de contraseñas con `bcrypt`/`passlib`
- **OCR:** Tesseract
- **Notificaciones:** Firebase Cloud Messaging
- **IA local (opcional):** Ollama, para el resumen ejecutivo del Agente Evaluador
- **Hosting:** Railway (API + PostgreSQL en el mismo proyecto), deploy automático en cada push a `main`

## Cómo levantarlo en local

Requiere Python 3.11+ y PostgreSQL 14+.

```bash
git clone https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Back
cd TP-IA-UTN-BiblioTech-Back

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# completar DATABASE_URL con tu Postgres local

python cargausuario.py   # crea el usuario administrador inicial
uvicorn main:app --reload
```

La API queda disponible en `http://localhost:8000`, con Swagger en `http://localhost:8000/docs`.

## Estado actual

Módulos conectados de punta a punta (backend ↔ frontend ↔ base de datos real): autenticación, catálogo, lectores, préstamos, reservas.

En desarrollo activo: enriquecimiento de las respuestas de circulación (algunos campos derivados se están completando en distintas rutas), y el flujo de activación de cuentas de lector recién creadas.

## Equipo

Ver detalle de roles en el informe final del proyecto.
