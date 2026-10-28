"""
The bot's view of the database.

Two groups:

* **Bot-owned** (created and migrated by Bot/migrations): bot_members,
  bot_notification_log.
* **Shared** (owned by the web API's migrations; the bot only maps them): users,
  buildings, defects, defect_comments, maintenance_jobs. Only the columns the
  bot touches are declared. tests/test_schema_contract.py checks them against
  the live database so a drifting API migration fails loudly, not at 2am.

The Postgres enum names must match the API's exactly (create_type=False: the
API created them, the bot must never try to).
"""

import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from botapp.db import Base

ROLES = ('admin', 'csr', 'building_executive', 'technician')


def _enum(*values, name):
    return Enum(*values, name=name, create_type=False)


# ---------------------------------------------------------------------------
# Shared tables (owned by the API)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(_enum(*ROLES, name='user_roles'), nullable=False)


class Building(Base):
    __tablename__ = 'buildings'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)


class Defect(Base):
    __tablename__ = 'defects'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(
        _enum('Open', 'Reviewed', 'Ongoing', 'Done', 'Completed', name='defect_statuses'),
        default='Open', nullable=False)
    priority = Column(_enum('low', 'medium', 'high', name='defect_priorities'), nullable=False)
    initial_report_image = Column(Text, nullable=True)
    building_id = Column(Integer, ForeignKey('buildings.id'), nullable=False)
    # Exactly one of the next two is set (CHECK in the API's migration f6a7b8c9d0e1).
    reporter_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    bot_reporter_id = Column(Integer, nullable=True)   # bot_members.id, deliberately no FK
    reporter_label = Column(String, nullable=True)     # display name captured at report time
    assigned_technician_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)

    technician = relationship('User', foreign_keys=[assigned_technician_id])
    building = relationship('Building', backref='defects')


class DefectComment(Base):
    __tablename__ = 'defect_comments'
    id = Column(Integer, primary_key=True)
    defect_id = Column(Integer, ForeignKey('defects.id'), nullable=False)
    initial_report = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)


class MaintenanceJob(Base):
    __tablename__ = 'maintenance_jobs'
    id = Column(Integer, primary_key=True)
    job_ref = Column(String(32), unique=True, nullable=False)
    category = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String, nullable=False)
    building_id = Column(Integer, ForeignKey('buildings.id'), nullable=True)
    maintenance_type = Column(_enum('Preventive', 'Corrective', name='maintenance_types'),
                              nullable=False)
    status = Column(_enum('Yet to Start', 'In Progress', 'Completed', name='maintenance_statuses'),
                    nullable=False)
    estimated_completion = Column(Date, nullable=True)
    next_job_date = Column(Date, nullable=True)
    schedule_note = Column(String, nullable=True)
    assigned_technician_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    building = relationship('Building', backref='maintenance_jobs')
    technician = relationship('User', foreign_keys=[assigned_technician_id])


# ---------------------------------------------------------------------------
# Bot-owned tables
# ---------------------------------------------------------------------------
class BotMember(Base):
    """
    The allowlist. A Telegram chat that is not in this table is refused.

    There are no roles: everyone listed has full access. `user_id` is an
    optional link to a web-app account (a "mapped member"); it only matters
    for "assigned to me" -- /myjobs, /mydefects and assignment alerts.
    """
    __tablename__ = 'bot_members'
    id = Column(Integer, primary_key=True)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=False)
    telegram_username = Column(String, nullable=True)
    display_name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    joined_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class BotNotificationLog(Base):
    """One row per assignment alert already delivered (or given up on)."""
    __tablename__ = 'bot_notification_log'
    __table_args__ = (UniqueConstraint('kind', 'ref_id', 'user_id', name='uq_bot_notification'),)
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False)       # 'defect' | 'job'
    ref_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)       # the assigned users.id at send time
    attempts = Column(Integer, default=0, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
