# SGB Backend — FastAPI

Backend del Sistema de Gestión de Bibliotecas (SGB).

## Requisitos

- Python 3.11+
- PostgreSQL 14+
- Tesseract OCR (opcional, para reconocimiento de fotos)

## Instalación

```bash
# 1. Clonar y entrar al proyecto
cd sgb_backend

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales de PostgreSQL y claves de API

# 5. Levantar el servidor
uvicorn main:app --reload
```

La API queda disponible en `http://localhost:8000`
Documentación interactiva (Swagger): `http://localhost:8000/docs`

## Estructura

```
sgb_backend/
├── main.py                        # Punto de entrada FastAPI
├── requirements.txt
├── .env.example
└── app/
    ├── api/v1/
    │   ├── router.py              # Agrupa todos los routers
    │   └── endpoints/
    │       ├── auth.py            # Login, JWT, Firebase token
    │       ├── lectores.py        # ABM de lectores
    │       ├── catalogo.py        # Títulos, ejemplares, OCR
    │       └── circulacion.py     # Préstamos, reservas, multas, dashboard
    ├── agents/
    │   ├── capture.py             # Agente de Captura (OCR + extracción ISBN)
    │   ├── analyzer.py            # Agente Analizador (enriquecimiento por ISBN)
    │   └── planner.py             # Agente Planificador (scheduler + push)
    ├── core/
    │   ├── config.py              # Settings desde .env
    │   ├── security.py            # JWT y hashing
    │   └── deps.py                # Dependencias FastAPI (auth, DB session)
    ├── db/
    │   └── session.py             # Engine async de SQLAlchemy
    ├── models/
    │   ├── usuario.py             # Usuario y Lector
    │   ├── libro.py               # Titulo y Ejemplar
    │   └── circulacion.py         # Prestamo, Reserva y Multa
    └── schemas/
        ├── usuario.py             # Pydantic schemas de auth y lectores
        ├── libro.py               # Pydantic schemas de catálogo y OCR
        └── circulacion.py         # Pydantic schemas de circulación y dashboard
```

## Endpoints principales

| Método | Ruta | Descripción | Rol mínimo |
|--------|------|-------------|------------|
| POST | `/api/v1/auth/login` | Obtener JWT | — |
| POST | `/api/v1/auth/firebase-token` | Registrar token push | lector |
| POST | `/api/v1/lectores/` | Alta de lector | bibliotecario |
| GET | `/api/v1/lectores/` | Listar/buscar lectores | bibliotecario |
| GET | `/api/v1/lectores/{id}` | Ficha completa del lector | bibliotecario |
| PATCH | `/api/v1/lectores/{id}` | Modificar lector | bibliotecario |
| DELETE | `/api/v1/lectores/{id}` | Baja lógica | bibliotecario |
| POST | `/api/v1/lectores/{id}/reactivar` | Reactivar | bibliotecario |
| GET | `/api/v1/catalogo/titulos` | Buscar títulos | lector |
| POST | `/api/v1/catalogo/titulos/captura-ocr` | Subir 3 fotos → OCR | bibliotecario |
| POST | `/api/v1/catalogo/titulos` | Confirmar alta de título | bibliotecario |
| POST | `/api/v1/catalogo/titulos/{id}/validar` | Publicar en catálogo | bibliotecario |
| POST | `/api/v1/catalogo/ejemplares` | Agregar ejemplar (genera QR) | bibliotecario |
| GET | `/api/v1/catalogo/ejemplares/qr/{qr}` | Buscar ejemplar por QR | bibliotecario |
| POST | `/api/v1/prestamos` | Registrar préstamo por QR | bibliotecario |
| POST | `/api/v1/prestamos/devolucion` | Registrar devolución por QR | bibliotecario |
| GET | `/api/v1/prestamos/lector/{id}` | Historial de préstamos | lector |
| POST | `/api/v1/reservas` | Solicitar reserva | lector |
| DELETE | `/api/v1/reservas/{id}` | Cancelar reserva | lector |
| GET | `/api/v1/multas/lector/{id}` | Ver multas | bibliotecario |
| PATCH | `/api/v1/multas/{id}` | Pagar/condonar multa | bibliotecario |
| GET | `/api/v1/dashboard/indicadores` | Métricas operativas | bibliotecario |

## Tesseract OCR (opcional)

Para habilitar el reconocimiento automático de fotos:

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng

# macOS
brew install tesseract tesseract-lang
```

Sin Tesseract instalado, el endpoint `/captura-ocr` devuelve campos vacíos
y el bibliotecario completa los datos manualmente (modo fallback offline).

## Firebase (notificaciones push)

1. Crear proyecto en Firebase Console
2. Descargar `firebase_credentials.json` (Service Account)
3. Colocar el archivo en la raíz del proyecto
4. Configurar `FIREBASE_CREDENTIALS_PATH=firebase_credentials.json` en `.env`

Sin Firebase configurado, las notificaciones se loguean en consola (modo debug).
