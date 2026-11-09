from sqlmodel import Column, Field, SQLModel
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB


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
