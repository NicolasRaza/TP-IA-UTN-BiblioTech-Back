# SGB Backend — FastAPI

Backend del Sistema de Gestión de Bibliotecas (SGB).

## Requisitos

- Python 3.11+
- PostgreSQL 14+

## Instalación paso a paso

### 1. Entrar al proyecto y crear el entorno virtual

```bash
cd sgb_backend
python3 -m venv venv
source venv/bin/activate
```

El prompt debe mostrar `(venv)` al inicio. Hay que activarlo cada vez que se abre una terminal nueva.

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar PostgreSQL

Primero instalá PostgreSQL si no lo tenés:

```bash
# Ubuntu/Debian
sudo apt install postgresql

# macOS
brew install postgresql
```

Luego creá el usuario y la base de datos (solo la primera vez):

```bash
sudo -u postgres psql
```

Dentro de psql, ejecutá:

```sql
CREATE USER sgb_user WITH PASSWORD 'sgb123';
CREATE DATABASE sgb_db OWNER sgb_user;
\q
```

### 4. Configurar el archivo .env

```bash
cp .env.example .env
```

Abrí el archivo `.env` y dejalo así (con los datos que creaste en el paso anterior):

```
DATABASE_URL=postgresql+asyncpg://sgb_user:sgb123@localhost:5432/sgb_db
SECRET_KEY=cualquier-cadena-larga-y-aleatoria-aca-123456
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

FIREBASE_CREDENTIALS_PATH=
GOOGLE_BOOKS_API_KEY=

MAX_DIAS_PRESTAMO_ADULTO=14
MAX_DIAS_PRESTAMO_INFANTIL=7
MAX_DIAS_PRESTAMO_DOCENTE=30
MAX_PRESTAMOS_SIMULTANEOS=3
HORAS_RESERVA_DISPONIBLE=48
```

> Las variables FIREBASE y GOOGLE_BOOKS se pueden dejar vacías para desarrollo.

### 5. Crear el usuario administrador

```bash
python cargausuario.py
```

Deberías ver:
```
✓ Usuario administrador creado
  Email:    admin@biblioteca.com
  Password: admin123
  Rol:      administrador
```

### 6. Levantar el servidor

```bash
uvicorn main:app --reload
```

La API queda disponible en `http://localhost:8000`  
Documentación interactiva (Swagger): `http://localhost:8000/docs`

### 7. Probar el login en Swagger

1. Entrá a `http://localhost:8000/docs`
2. Buscá `POST /api/v1/auth/login`
3. Ingresá:
```json
{
  "email": "admin@biblioteca.com",
  "password": "admin123"
}
```
4. Copiá el `access_token` de la respuesta
5. Hacé clic en **Authorize** (arriba a la derecha) y pegá el token
6. Todos los endpoints quedan habilitados

---

## Estructura del proyecto

```
sgb_backend/
├── main.py                        # Punto de entrada FastAPI
├── requirements.txt
├── .env.example
├── cargausuario.py                # Script para crear el primer administrador
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

## Firebase (notificaciones push, opcional)

1. Crear proyecto en Firebase Console
2. Descargar `firebase_credentials.json` (Service Account)
3. Colocar el archivo en la raíz del proyecto
4. Configurar `FIREBASE_CREDENTIALS_PATH=firebase_credentials.json` en `.env`

Sin Firebase configurado, las notificaciones se loguean en consola (modo debug).
