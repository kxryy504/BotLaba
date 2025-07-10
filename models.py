# models.py
import os
from datetime import date
from sqlalchemy import (
    Column, Integer, String, Date, Boolean,
    ForeignKey, Table, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from dotenv import load_dotenv

load_dotenv()  # загрузим .env из корня проекта

Base = declarative_base()

# Таблица связи «событие ↔ получатель»
event_recipients = Table(
    'event_recipients', Base.metadata,
    Column('event_id', Integer, ForeignKey('events.id'), primary_key=True),
    Column('user_id',  Integer, ForeignKey('users.id'),  primary_key=True),
)

class User(Base):
    __tablename__ = 'users'
    id            = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id   = Column(Integer, unique=True, nullable=False)
    full_name     = Column(String(255), nullable=False)
    position      = Column(String(100), nullable=False)
    birth_date    = Column(Date, nullable=False)
    is_admin      = Column(Boolean, default=False, nullable=False)

    events_created   = relationship("Event", back_populates="creator")
    events_to_notify = relationship(
        "Event",
        secondary=event_recipients,
        back_populates="recipients"
    )

class Event(Base):
    __tablename__ = 'events'
    id           = Column(Integer, primary_key=True, autoincrement=True)
    title        = Column(String(255), nullable=False)
    description  = Column(String, nullable=False)
    event_date   = Column(Date, nullable=False)
    creator_id   = Column(Integer, ForeignKey('users.id'), nullable=False)

    creator      = relationship("User", back_populates="events_created")
    recipients   = relationship(
        "User",
        secondary=event_recipients,
        back_populates="events_to_notify"
    )
    reminders    = relationship("Reminder", back_populates="event", cascade="all, delete-orphan")

class Reminder(Base):
    __tablename__ = 'reminders'
    id             = Column(Integer, primary_key=True, autoincrement=True)
    event_id       = Column(Integer, ForeignKey('events.id'), nullable=False)
    interval_days  = Column(Integer, nullable=False)
    event          = relationship("Event", back_populates="reminders")

# Поддерживаем чтение URL БД из .env, или дефолт
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot_database.db')
engine = create_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    """При первом запуске создаём таблицы и администратора."""
    # путь к файлу sqlite берётся из DATABASE_URL
    # для sqlite: sqlite:///path/to/file.db
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(db_path):
            return
    else:
        # для других СУБД можно не проверять файл
        pass

    # создаём все таблицы
    Base.metadata.create_all(engine)

    # Telegram ID админа из .env
    admin_tid = os.getenv('ADMIN_TELEGRAM_ID')
    if not admin_tid:
        raise RuntimeError("В .env не задан ADMIN_TELEGRAM_ID")
    admin_tid = int(admin_tid)

    session = SessionLocal()
    admin = User(
        telegram_id=admin_tid,
        full_name=os.getenv('ADMIN_FULL_NAME', 'Администратор'),
        position=os.getenv('ADMIN_POSITION', 'Администратор'),
        birth_date=date.fromisoformat(os.getenv('ADMIN_BIRTH_DATE', '1980-01-01')),
        is_admin=True
    )
    session.add(admin)
    session.commit()
    session.close()

if __name__ == '__main__':
    init_db()
