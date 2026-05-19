from datetime import datetime, timezone
import os
from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy import Column, delete
from dotenv import load_dotenv
from scrape import get_finnhub_client
from models import Verdict
import time

load_dotenv()


# DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def db_empty():
    with Session(engine) as session:
        count = session.exec(select(Verdict)).all()
        return len(count) == 0

def store_verdicts(verdicts: dict, profiles: dict):
    finnhub_client = get_finnhub_client()
    with Session(engine) as session:
        for ticker, verdict_data in verdicts.items():
            profile = profiles.get(ticker, {})  

            # NOTE: there is also a 60/min rate limit
            if (list(verdicts.keys())).index(ticker) % 25 == 0  and (list(verdicts.keys())).index(ticker) != 0: # prevents finnhub rate limit of 30 calls/second
                time.sleep(1)
            price_data = finnhub_client.quote(ticker)

            existing = session.exec(
                select(Verdict).where(Verdict.ticker == ticker)
            ).first()
            
            if existing:
                existing.data = verdict_data
                existing.company_name = profile.get("name")
                existing.industry = profile.get("finnhubIndustry")
                existing.description = profile.get("description") 
                existing.logo_url = profile.get("logo")
                existing.updated_at = datetime.now(timezone.utc)
                existing.interesting_ticker = verdict_data["interesting_ticker"] # may change to False on update
                existing.days_alive = existing.days_alive + 1
                existing.current_price = price_data["c"]
                session.add(existing)
            else:
                row = Verdict(
                    ticker=ticker,
                    data=verdict_data,
                    company_name=profile.get("name"),
                    industry=profile.get("finnhubIndustry"),
                    description=profile.get("description"),
                    logo_url=profile.get("logo"),
                    interesting_ticker=verdict_data["interesting_ticker"], # decides to keep it or not
                    price_at_generation = price_data["c"] # current price from finnhub e.g. 261.74 (type=float)
                )
                session.add(row)
        
        session.commit()
        print(f"Stored {len(verdicts)} tickers in Postgres")

def get_all_verdicts():
    with Session(engine) as session:
        rows = session.exec(select(Verdict)).all()
        print(rows)
        return {row.ticker: {
            "verdict_data": row.data,
            "company_name": row.company_name,
            "industry": row.industry,
            "description": row.description,
            "logo_url": row.logo_url,
            "updated_at": row.updated_at.isoformat(),
            "interesting_ticker": row.interesting_ticker,
            "days_alive": row.days_alive
        } for row in rows}
    
def delete_all_veridcts():
    with Session(engine) as session:
        session.exec(delete(Verdict))
        session.commit()
        print("deleted verdict table contents")

def delete_uninteresting_tickers():
    with Session(engine) as session:
        session.exec(delete(Verdict).where(Verdict.interesting_ticker == False))
        session.commit()
        print("deleted tickers with interesting_ticker set to False")

def get_interesting_ticker():
    with Session(engine) as session:
        rows = session.exec(select(Verdict).where(Verdict.interesting_ticker == True)).all()
        return [row.ticker for row in rows] # only want the ticker -> verdict will be be generated fresh.
    
if __name__ == "__main__":
    create_db_and_tables()