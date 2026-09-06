import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Для старта — SQLite (файл рядом с проектом).
# Для продакшена просто задайте переменную окружения DATABASE_URL,
# например: postgresql://user:password@host:5432/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tracker.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
