import asyncio
from sqlalchemy import select
from app.db.session import engine, Base, AsyncSessionLocal
from app.models.usuario import Usuario, RolUsuario
from app.models.libro import Titulo, Ejemplar  # noqa
from app.models.circulacion import Prestamo, Reserva, Multa  # noqa
from app.core.security import hashear_password


async def main():
    # 1. Crear tablas si no existen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Crear o verificar usuario administrador
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Usuario).where(Usuario.email == "admin@biblioteca.com"))
        admin_existente = res.scalar_one_or_none()

        if admin_existente:
            print("ℹ El usuario administrador ya existe.")
        else:
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


if __name__ == "__main__":
    asyncio.run(main())
