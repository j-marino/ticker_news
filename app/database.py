import redis
import json
from datetime import timedelta
from scrape import generate_all_verdicts, get_recommendation_data, finnhub_client
from dotenv import load_dotenv

load_dotenv()

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def store_verdicts():
    ticker_to_data = generate_all_verdicts(get_recommendation_data(finnhub_client))

    for ticker, verdict in ticker_to_data.items():
        r.hset("verdicts", ticker, json.dumps(verdict))
    
    # expire the whole hash after 24 hours
    r.expire("verdicts", timedelta(hours=24))
    print(f"Stored {len(ticker_to_data)} tickers in Redis")

def get_verdict(ticker):
    data = r.hget("verdicts", ticker)
    return json.loads(data) if data else None

def get_all_verdicts():
    all_data = r.hgetall("verdicts")
    return {ticker: json.loads(verdict) for ticker, verdict in all_data.items()}

if __name__ == "__main__":
    store_verdicts()