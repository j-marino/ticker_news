import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlmodel import SQLModel, create_engine

from database import get_all_verdicts


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


async def run_populate():
    from cron_populate_db import populate

    await asyncio.to_thread(populate)


async def populate_background():
    from cron_populate_db import populate

    print("imported cron populate")
    try:
        print("Background db population starting...")
        await asyncio.to_thread(populate)
        print("Background populate complete")
    except Exception as e:
        print(f"Background populate failed: {e}")


async def run_depopulate():
    from cron_depopulate_db import depopulate

    await asyncio.to_thread(depopulate)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    asyncio.create_task(populate_background())

    scheduler.add_job(run_depopulate, CronTrigger(hour=6, minute=45, day_of_week="mon-fri"))
    scheduler.add_job(run_populate, CronTrigger(hour=7, minute=0, day_of_week="mon-fri"))

    scheduler.start()
    yield
    scheduler.shutdown()


limiter = Limiter(key_func=get_remote_address)
scheduler = AsyncIOScheduler()
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def dashboard(request: Request):
    tickers = get_all_verdicts()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tickers": tickers},
    )
