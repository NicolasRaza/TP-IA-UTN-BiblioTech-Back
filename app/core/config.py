from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/sgb_db"
    SECRET_KEY: str = "cambia-esto-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    GOOGLE_BOOKS_API_KEY: Optional[str] = None

    # Plazos parametrizables por categoría
    MAX_DIAS_PRESTAMO_ADULTO: int = 14
    MAX_DIAS_PRESTAMO_INFANTIL: int = 7
    MAX_DIAS_PRESTAMO_DOCENTE: int = 30
    MAX_PRESTAMOS_SIMULTANEOS: int = 3
    HORAS_RESERVA_DISPONIBLE: int = 48

    class Config:
        env_file = ".env"


settings = Settings()
