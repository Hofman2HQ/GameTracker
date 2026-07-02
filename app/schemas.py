
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import STATUSES

DATE_PATTERN = r'^\d{4}-\d{2}-\d{2}$'


class GameBase(BaseModel):
    rawg_id: int
    slug: str
    name: str
    background_image: str | None = None
    released: str | None = None
    metacritic: int | None = None
    description: str | None = None
    genres: list[str] | None = None
    platforms: list[str] | None = None


class GameOut(GameBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class EntryBase(BaseModel):
    status: str = Field(default='PLAN')
    rating: int | None = Field(default=None, ge=0, le=10)
    comment: str | None = Field(default=None, max_length=4000)
    hours_played: float | None = Field(default=None, ge=0.0)
    favorite: bool = False
    start_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    end_date: str | None = Field(default=None, pattern=DATE_PATTERN)

    @field_validator('status')
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        if value not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        return value


class EntryCreate(EntryBase):
    rawg_id: int


class EntryUpdate(EntryBase):
    pass


class EntryOut(EntryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game: GameOut
