import asyncio
from app.db.session import engine, Base

# Importar TODOS los modelos antes de crear tablas
from app.models.usuario import Usuario, RolUsuario
from app.models.libro import Titulo, Ejemplar          # noqa
from app.models.circulacion import Prestamo, Reserva, Multa  # noqa

from app.core.security import hashear_password
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        admin = Usuario(
            email="admin@biblioteca.com",
            password_hash=hashear_password("admin123"),
            rol=RolUsuario.ADMINISTRADOR,
            activo=True,
        )
        db.add(admin)
        await db.commit()
        print("✓ Usuario administrador creado")
        print("  Email:    admin@biblioteca.com")
        print("  Password: admin123")
        print("  Rol:      administrador")


asyncio.run(main())
