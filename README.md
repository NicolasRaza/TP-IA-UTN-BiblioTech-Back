# BiblioTech — Backend

## Entrega Final - Proyecto en vivo

🔗 **API en producción:** https://tp-ia-utn-bibliotech-back-production.up.railway.app/
📄 **Documentación interactiva (Swagger):** https://tp-ia-utn-bibliotech-back-production.up.railway.app/docs

Para probar los endpoints protegidos, hay que loguearse primero — no hay credenciales de administrador precargadas en el propio Swagger, se obtienen haciendo login por `/api/v1/auth/login`.

## Sobre el proyecto

BiblioTech es un sistema de gestión de bibliotecas (SGB), y este repositorio es su **backend**: la API que sirve el catálogo, los préstamos, las reservas y el padrón de lectores, y que aloja a los cinco agentes de IA que automatizan la parte más repetitiva del trabajo bibliotecario — leer un libro nuevo con la cámara y completar su ficha solos, armar y avisar la cola de reservas, y resumir en una frase qué necesita atención hoy.

El backend sigue el mismo ciclo que describe el diseño conceptual del proyecto: Observación → Análisis → Decisión → Acción, con el Agente Evaluador decidiendo qué corresponde hacer y el Agente Planificador ejecutándolo — separados por diseño, para que uno nunca pueda actuar sin que el otro lo haya decidido antes.

## Funcionalidades principales

- **Catálogo**: alta de títulos y ejemplares, cada uno con su código QR único
- **Circulación**: préstamos, devoluciones, reservas con cola y multas por atraso
- **Padrón de lectores**: alta, categorías (infantil, adolescente, adulto, docente, institucional) y baja lógica
- **Agentes de IA**:
  - **Captura + Analizador** → OCR de 3 fotos del libro, enriquecimiento por ISBN
  - **Planificador** → gestiona la cola de reservas y dispara notificaciones push
  - **Evaluador** → resume el estado de la biblioteca en lenguaje natural
  - **Aprendizaje** → ajusta las recomendaciones según el historial de cada lector
- **Autenticación** por rol (lector, bibliotecario, administrador) con JWT

## Enlaces del proyecto

| Recurso | Link |
|---|---|
| **Repositorio frontend** | https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Front |
| **Aplicación web (producción)** | https://nicolasraza.github.io/TP-IA-UTN-BiblioTech-Front/ |
| **Informe final del proyecto** | https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Informe |

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

## Documentación completa

Arquitectura detallada, diagramas (ERD, UML), evaluación de UX/UI y ciberseguridad, y evidencia de funcionamiento están en el [informe final del proyecto](https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Informe).

## Contribuir

¿Vas a tocar código? Mirá [CONTRIBUTING.md](./CONTRIBUTING.md) antes de abrir un PR.

## Equipo

Ver detalle de roles en el [informe final del proyecto](https://github.com/NicolasRaza/TP-IA-UTN-BiblioTech-Informe).
