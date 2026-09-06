from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    purchases = relationship("Purchase", back_populates="user", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    icon = Column(String, default="🛒")
    color = Column(String, default="#6C5CE7")

    user = relationship("User", back_populates="categories")


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=True)
    date = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="purchases")
    category = relationship("Category")


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # category_id = None -> это общий (overall) бюджет на период
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    limit_amount = Column(Float, nullable=False)
    period = Column(String, default="month")  # month | week

    user = relationship("User", back_populates="budgets")
    category = relationship("Category")
