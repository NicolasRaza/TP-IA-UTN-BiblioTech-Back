from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://sgb_user:sgb123@localhost:5432/sgb_db"
    SECRET_KEY: str = "cambia-esto-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    GOOGLE_BOOKS_API_KEY: Optional[str] = "AIzaSyC4NXd1no02chR0VjWvjeLRFIxAbvq2V2Y"

    # Plazos parametrizables por categoría
    MAX_DIAS_PRESTAMO_ADULTO: int = 14
    MAX_DIAS_PRESTAMO_INFANTIL: int = 7
    MAX_DIAS_PRESTAMO_DOCENTE: int = 30
    MAX_PRESTAMOS_SIMULTANEOS: int = 3
    HORAS_RESERVA_DISPONIBLE: int = 48

    model_config = SettingsConfigDict(
        env_file=(str(ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

