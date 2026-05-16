import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    directory = Column(String, nullable=False)
    description = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.datetime.now)
    last_used_at = Column(DateTime, default=datetime.datetime.now)
    calculations = relationship('Calculation', back_populates='project', cascade='all, delete-orphan')


class Calculation(Base):
    __tablename__ = 'calculations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    mode = Column(String, nullable=False)
    model_name = Column(String, default='')
    status = Column(String, default='running')
    started_at = Column(DateTime, default=datetime.datetime.now)
    finished_at = Column(DateTime, nullable=True)
    result_dir = Column(String, default='')
    input_snapshot = Column(Text, default='')
    summary = Column(Text, default='')
    memo = Column(Text, default='')
    use_max_thread = Column(Boolean, default=False)
    error_message = Column(Text, default='')
    project = relationship('Project', back_populates='calculations')
