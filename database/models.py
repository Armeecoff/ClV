from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    ForeignKey, Integer, String, Text, Enum
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class UpgradeType(str, enum.Enum):
    click = "click"
    autoclk = "autoclk"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    balance = Column(Float, default=0.0, nullable=False)
    total_clicks = Column(BigInteger, default=0, nullable=False)
    clicks_per_click = Column(Integer, default=1, nullable=False)
    auto_clicks_per_second = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    premium_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    upgrades = relationship("UserUpgrade", back_populates="user")
    vpn_purchases = relationship("VPNPurchase", back_populates="user")
    activity_logs = relationship("UserActivityLog", back_populates="user", cascade="all, delete-orphan")


class ClickUpgrade(Base):
    __tablename__ = "click_upgrades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    upgrade_type = Column(String(10), default="click", nullable=False)
    clicks_bonus = Column(Integer, nullable=False, default=0)
    auto_click_bonus = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True, nullable=False)
    is_premium_only = Column(Boolean, default=False, nullable=False)
    icon = Column(String(10), default="⚡", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user_upgrades = relationship("UserUpgrade", back_populates="upgrade")


class UserUpgrade(Base):
    __tablename__ = "user_upgrades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    upgrade_id = Column(Integer, ForeignKey("click_upgrades.id"), nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="upgrades")
    upgrade = relationship("ClickUpgrade", back_populates="user_upgrades")


class VPNConfig(Base):
    __tablename__ = "vpn_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    config_data = Column(Text, nullable=False)
    price_clicks = Column(Float, nullable=False)
    duration_days = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    quantity_left = Column(Integer, nullable=False, default=1)
    available_until = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(BigInteger, nullable=True)

    purchases = relationship("VPNPurchase", back_populates="vpn_config")


class VPNPurchase(Base):
    __tablename__ = "vpn_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vpn_config_id = Column(Integer, ForeignKey("vpn_configs.id"), nullable=False)
    price_paid = Column(Float, nullable=False)
    purchased_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="vpn_purchases")
    vpn_config = relationship("VPNConfig", back_populates="purchases")


class UserActivityLog(Base):
    __tablename__ = "user_activity_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    action_type = Column(String(30), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="activity_logs")


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(10), default="🎉", nullable=False)
    promo_type = Column(String(20), default="click_mult", nullable=False)
    value = Column(Float, default=2.0, nullable=False)
    end_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
