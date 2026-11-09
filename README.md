# $tackz

$tackz is a public stock-news dashboard that combines market news, analyst and insider data, and technical indicators to generate AI-written ticker verdicts. The verdicts are informational, not financial advice.

There is no login or email registration. Visiting the deployed site opens the ticker dashboard directly at `/`. Watchlists are saved in the current browser using local storage and are not shared across browsers or devices.

## Requirements

- Python 3.14+ (the included Docker image uses Python 3.14)
- PostgreSQL database
- API credentials for the data and AI services below

## Configure environment

Create a `.env` file in the project root (or set these variables in your deployment platform):

```dotenv
DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE"

GEMINI_API_KEY=""
MARKETAUX_API_KEY=""
FINN_API_KEY=""
ALPHA_VANTAGE_API_KEY=""
```

Create the PostgreSQL database before starting the app. Keep API keys private and do not commit `.env`. Use any SSL options required by your database provider in `DATABASE_URL`.

Get API credentials from [Google AI Studio](https://aistudio.google.com/apikey), [Marketaux](https://www.marketaux.com/), [Finnhub](https://finnhub.io/), and [Alpha Vantage](https://www.alphavantage.co/support/#api-key).

The AI integration tries a pool of Gemini models in sequence when a model is rate-limited or fails. This can help make use of Gemini's free-tier quotas, subject to Google's current availability, limits, and terms. The model list is in `app/scrape.py`; you can change it or adapt the integration to use your own models and provider.

## Run locally

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --app-dir app --host 0.0.0.0 --port 8000
```

With valid configuration and a reachable database, open <http://localhost:8000>. The app creates its tables at startup and starts an initial background data population. It also schedules weekday data refreshes in UTC.

## Deploy with Docker

Build the image from the project root:

```bash
docker build -t ticker-news .
```

Run it with your environment file:

```bash
docker run --name ticker-news --env-file .env -p 8000:8000 ticker-news
```

For hosted deployment, build from this repository using the included `Dockerfile`, set the environment variables in the platform's secret/configuration settings, and expose port `8000`. Provide a persistent PostgreSQL service and set `DATABASE_URL` to its connection string. The service must be able to reach the external APIs; initial ticker population runs in the background after startup.

## Notes

- The app listens on `0.0.0.0:8000` in Docker. Its public ticker dashboard is served at `/` (and `/dashboard`).
- Scheduled depopulation and population run on weekdays at 06:45 and 07:00 UTC.
- API free tiers, model availability, and provider limits can change; check each provider's current terms and quotas.



