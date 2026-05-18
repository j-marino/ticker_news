from sqlmodel import Column, Field, SQLModel
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class User(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(default=None, index=True)
    email: EmailStr = Field(default=None, index=True)
    disabled: bool | None


class UserInDB(User, table=True):
    hashed_password: str


class UnverifiedUser(User, table=True):
    hashed_password: str
    creation_time: datetime
    generated_code: int


class UserPublic(BaseModel):
    username: str
    email: EmailStr


class WatchList(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key='userindb.id')
    ticker: str = Field(default=None, index=True, unique=True)
    company_name: str | None = None
    industry: str | None = None
    description: str | None = None
    logo_url: str | None = None


class Verdict(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(default=None, index=True, unique=True)
    company_name: str | None = None
    industry: str | None = None
    description: str | None = None
    logo_url: str | None = None
    data: dict = Field(default={}, sa_column=Column(JSONB))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    interesting_ticker: bool | None = Field(default=False)
    days_alive: int | None = Field(default=0)
    price_at_generation: float | None = Field(default=0)
    current_price: float | None = Field(default=0) # needs to be updated every n minutes
