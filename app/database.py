from datetime import datetime, timezone
import os
import json
from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy import Column, text, delete
from sqlalchemy.dialects.postgresql import JSONB
from dotenv import load_dotenv

load_dotenv()

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


DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def db_empty():
    with Session(engine) as session:
        query = session.exec(select(Verdict).where(Verdict.id == 1)).first()
        return query is None


def store_verdicts(verdicts: dict, profiles: dict):
    with Session(engine) as session:
        for ticker, verdict_data in verdicts.items():
            profile = profiles.get(ticker, {})
            
            existing = session.exec(
                select(Verdict).where(Verdict.ticker == ticker)
            ).first()
            
            if existing:
                existing.data = verdict_data
                existing.company_name = profile.get("name")
                existing.industry = profile.get("finnhubIndustry")
                existing.description = profile.get("description")  # change to the yfinance desc....
                existing.logo_url = profile.get("logo")
                existing.updated_at = datetime.now(timezone.utc)
                session.add(existing)
            else:
                row = Verdict(
                    ticker=ticker,
                    data=verdict_data,
                    company_name=profile.get("name"),
                    industry=profile.get("finnhubIndustry"),
                    description=profile.get("description"),
                    logo_url=profile.get("logo"),
                )
                session.add(row)
        
        session.commit()
        print(f"Stored {len(verdicts)} tickers in Postgres")

def get_all_verdicts():
    with Session(engine) as session:
        rows = session.exec(select(Verdict)).all()
        return {row.ticker: {
            "verdict_data": row.data,
            "company_name": row.company_name,
            "industry": row.industry,
            "description": row.description,
            "logo_url": row.logo_url,
            "updated_at": row.updated_at.isoformat()
        } for row in rows}
    
def delete_all_veridcts():
    with Session(engine) as session:
        session.exec(delete(Verdict))
        session.commit()
        print("deleted verdict table contents")

if __name__ == "__main__":
    create_db_and_tables()