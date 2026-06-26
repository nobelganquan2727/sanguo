import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '123456')
MYSQL_DB = os.getenv('MYSQL_DB', 'sanguo')

DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"

# Connection pool setup
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Feedback(Base):
    __tablename__ = 'feedback'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(255), nullable=False)
    event_title = Column(String(255), nullable=False)
    field_name = Column(String(255), nullable=False)
    proposed_value = Column(Text, nullable=False)
    status = Column(String(50), default='pending')
    created_at = Column(DateTime, server_default=func.now())

class UserProfile(Base):
    """Stores persistent user preferences and traits across all sessions."""
    __tablename__ = 'user_profiles'

    user_id = Column(String(255), primary_key=True)
    preference = Column(String(50), default='detailed')  # detailed or concise
    knowledge_level = Column(String(50), default='expert')  # beginner or expert
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationship to detailed topic memories
    memories = relationship("UserMemory", back_populates="user", cascade="all, delete-orphan")

class UserMemory(Base):
    """Stores summaries of topics/characters already discussed with the user."""
    __tablename__ = 'user_memories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('user_profiles.user_id', ondelete='CASCADE'), nullable=False)
    topic = Column(String(255), nullable=False)  # E.g., "曹操", "官渡之战"
    summary = Column(Text, nullable=False)  # Summary of what was discussed
    last_discussed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("UserProfile", back_populates="memories")

class Share(Base):
    """Stores shared Q&A results for WeChat and web sharing."""
    __tablename__ = 'shares'

    id = Column(String(50), primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
