"""Who is acting. A plain value, so it survives leaving the database session."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Actor:
    member_id: int
    name: str
    # The web account this member is mapped to, if an admin mapped one. Bot-only
    # members have None, and "assigned to me" can never match them.
    user_id: Optional[int] = None
    tier: str = 'end_user'

    @property
    def is_master(self):
        return self.tier == 'master_control'

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

