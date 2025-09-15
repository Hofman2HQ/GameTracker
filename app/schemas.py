from pydantic import BaseModel, Field
from typing import Optional, List

class GameBase(BaseModel):
    rawg_id: int
    slug: str
    name: str
    background_image: Optional[str] = None
    released: Optional[str] = None
    metacritic: Optional[int] = None
    genres: Optional[List[str]] = None
    platforms: Optional[List[str]] = None

class GameOut(GameBase):
    id: int
    class Config:
        from_attributes = True

class EntryBase(BaseModel):
    status: str = Field(default='PLAN')
    rating: Optional[int] = Field(default=None, ge=0, le=10)
    comment: Optional[str] = None
    hours_played: Optional[float] = None
    favorite: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class EntryCreate(EntryBase):
    rawg_id: int

class EntryUpdate(EntryBase):
    pass

class EntryOut(EntryBase):
    id: int
    game: GameOut
    class Config:
        from_attributes = True
