from datetime import datetime, timedelta, timezone
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    ForeignKey, Integer, String, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship

MSK = timezone(timedelta(hours=3))

def now_msk() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


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
    max_balance = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    premium_until = Column(DateTime, nullable=True)
    autobuy_enabled = Column(Boolean, default=False, nullable=False)
    autobuy_keywords = Column(Text, nullable=True)
    autobuy_min_price = Column(Float, nullable=True)
    autobuy_max_price = Column(Float, nullable=True)
    autobuy_max_count = Column(Integer, nullable=True)
    login_days_count = Column(Integer, default=0, nullable=False)
    login_streak = Column(Integer, default=0, nullable=False)
    last_login_date = Column(DateTime, nullable=True)
    profile_bio = Column(String(200), nullable=True)
    profile_badge = Column(String(20), nullable=True)
    vpn_notify_enabled = Column(Boolean, default=False, nullable=False)
    offline_income_enabled = Column(Boolean, default=False, nullable=False)
    last_offline_check = Column(DateTime, nullable=True)
    equipped_avatar = Column(String(20), default="👤", nullable=False)
    equipped_frame = Column(String(200), default="", nullable=False)
    created_at = Column(DateTime, default=now_msk, nullable=False)

    upgrades = relationship("UserUpgrade", back_populates="user")
    vpn_purchases = relationship("VPNPurchase", back_populates="user")
    activity_logs = relationship("UserActivityLog", back_populates="user", cascade="all, delete-orphan")
    achievements = relationship("UserAchievement", back_populates="user", cascade="all, delete-orphan")
    owned_avatars = relationship("UserAvatar", back_populates="user", cascade="all, delete-orphan")
    api_key = relationship("ApiKey", back_populates="user", uselist=False, cascade="all, delete-orphan")


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
    created_at = Column(DateTime, default=now_msk, nullable=False)

    user_upgrades = relationship("UserUpgrade", back_populates="upgrade")


class UserUpgrade(Base):
    __tablename__ = "user_upgrades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    upgrade_id = Column(Integer, ForeignKey("click_upgrades.id"), nullable=False)
    purchased_at = Column(DateTime, default=now_msk, nullable=False)

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
    is_premium_only = Column(Boolean, default=False, nullable=False)
    notify_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=now_msk, nullable=False)
    created_by = Column(BigInteger, nullable=True)

    purchases = relationship("VPNPurchase", back_populates="vpn_config")


class VPNPurchase(Base):
    __tablename__ = "vpn_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vpn_config_id = Column(Integer, ForeignKey("vpn_configs.id"), nullable=False)
    price_paid = Column(Float, nullable=False)
    purchased_at = Column(DateTime, default=now_msk, nullable=False)
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
    created_at = Column(DateTime, default=now_msk, nullable=False)

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
    created_at = Column(DateTime, default=now_msk, nullable=False)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(20), default="🏆", nullable=False)
    condition_type = Column(String(50), nullable=False)
    condition_value = Column(Text, default="0", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_msk, nullable=False)

    user_achievements = relationship("UserAchievement", back_populates="achievement", cascade="all, delete-orphan")


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    achievement_id = Column(Integer, ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False)
    unlocked_at = Column(DateTime, default=now_msk, nullable=False)

    user = relationship("User", back_populates="achievements")
    achievement = relationship("Achievement", back_populates="user_achievements")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=now_msk, onupdate=now_msk, nullable=False)


class Avatar(Base):
    __tablename__ = "avatars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    emoji = Column(String(20), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    description = Column(String(200), nullable=True)
    item_type = Column(String(10), default="avatar", nullable=False)
    border_css = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    owners = relationship("UserAvatar", back_populates="avatar")


class UserAvatar(Base):
    __tablename__ = "user_avatars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    avatar_id = Column(Integer, ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False)
    purchased_at = Column(DateTime, default=now_msk, nullable=False)

    user = relationship("User", back_populates="owned_avatars")
    avatar = relationship("Avatar", back_populates="owners")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    max_activations = Column(Integer, nullable=False)
    activations_used = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=now_msk, nullable=False)

    activations = relationship("PromoCodeActivation", back_populates="promo_code", cascade="all, delete-orphan")


class PromoCodeActivation(Base):
    __tablename__ = "promo_code_activations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activated_at = Column(DateTime, default=now_msk, nullable=False)

    promo_code = relationship("PromoCode", back_populates="activations")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=now_msk, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_key")
