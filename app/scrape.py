import finnhub
import http.client, urllib.parse
import os
import json
import time

from google.genai import types
from google import genai
from collections import Counter
from dotenv import load_dotenv
from datetime import date, timedelta
from technical_indicators import get_technicals, get_support_resistance
from vantage_intel import extract_av_tickers
import yfinance as yf
import requests

load_dotenv()
url = 'https://api.finnhub.io'
requests.get(url, timeout=30)


# Gemini model fallback chain
GEMINI_MODELS = [
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.0-flash',
]

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def call_gemini(prompt: str, system_instruction: str) -> str:
    # each model in order, falling back on rate limit or error
    for model in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    thinking_config=types.ThinkingConfig(thinking_budget=-1)
                ),
                contents=prompt
            )
            raw = response.text.strip()
            if raw:
                return raw
        except Exception as e:
            err = str(e).lower()
            if "quota" in err or "rate" in err or "429" in err or "exhausted" in err:
                print(f"Model {model} rate limited, trying next...")
                time.sleep(3)
                continue
            else:
                print(f"Model {model} failed with: {e}")
                continue
    raise ValueError("All Gemini models exhausted or failed")


def get_marketaux_data(): # -> parsed
    conn = http.client.HTTPSConnection('api.marketaux.com')
    params = urllib.parse.urlencode({
        'api_token': os.getenv("MARKETAUX_API_KEY"),
        'industries': 'Technology',
        'countries': 'us,uk',
        'sentiment_gte': -1,
        'limit': 100,
        'language': 'en'
    })
    conn.request('GET', '/v1/news/all?{}'.format(params))
    res = conn.getresponse()
    return json.loads(res.read().decode('utf-8'))


def get_finnhub_client():
    return finnhub.Client(api_key=os.getenv("FINN_API_KEY"))


def extract_trending_tickers(articles):
    symbols = []
    for article in articles["data"]:
        for entity in article["entities"]:
            if entity["sentiment_score"] is not None:
                symbols.append({
                    "symbol": entity["symbol"],
                    "sentiment": entity["sentiment_score"]
                })
    
    # count mentions
    mentions = Counter(s["symbol"] for s in symbols)
    
    # average sentiment per ticker
    ticker_sentiment = {}
    for ticker in mentions:
        scores = [s["sentiment"] for s in symbols if s["symbol"] == ticker]
        ticker_sentiment[ticker] = {
            "mentions": mentions[ticker],
            "avg_sentiment": sum(scores) / len(scores),
            "signal": "bullish" if sum(scores)/len(scores) > 0.1 
                      else "bearish" if sum(scores)/len(scores) < -0.1 
                      else "neutral"
        }
    
    # return top 10 by mentions
    return sorted(ticker_sentiment.items(), key=lambda x: x[1]["mentions"], reverse=True)[:10]


def get_quality_earnings_tickers(finnhub_client):
    today = date.today().strftime('%Y-%m-%d')
    next_week = (date.today() + timedelta(days=7)).strftime('%Y-%m-%d')
    earnings = finnhub_client.earnings_calendar(
        _from=today, to=next_week, symbol="", international=False
    )
    tickers = []
    for e in earnings.get('earningsCalendar', []):
        # only include if estimated EPS exists (filters out tiny unknowns)
        # and revenue estimate is significant
        if (e.get('epsEstimate') is not None and
            e.get('revenueEstimate') and
            e['revenueEstimate'] > 670_000_000): # $670M+ revenue companies only
            tickers.append(e['symbol'])
            
    return tickers


def get_final_watchlist(finnhub_client, parsed):
    news_tickers = [t[0] for t in extract_trending_tickers(parsed)]
    earnings_tickers = get_quality_earnings_tickers(finnhub_client)
    av_tickers = [t["ticker"] for t in extract_av_tickers()]
    merged = list(set(news_tickers + earnings_tickers + av_tickers))
    return merged[:15]


def get_recommendation_data(finnhub_client, parsed):
    ticker_list = get_final_watchlist(finnhub_client, parsed)
    today = date.today().strftime('%Y-%m-%d')
    last_month = (date.today() - timedelta(days=31)).strftime('%Y-%m-%d')
    next_week = (date.today() + timedelta(days=7)).strftime('%Y-%m-%d')

    earnings_calendar = finnhub_client.earnings_calendar(
        _from=today, to=next_week, symbol="", international=False
    ).get('earningsCalendar', [])
    earnings_by_ticker = {e['symbol']: e for e in earnings_calendar}

    ticker_to_data = {}
    for ticker in ticker_list:
        try:
            technicals = get_technicals(ticker)
            sr = get_support_resistance(ticker)
        except Exception:
            continue

        ticker_to_data[ticker] = {
            "trends": finnhub_client.recommendation_trends(ticker),
            "insider transactions": finnhub_client.stock_insider_transactions(ticker, last_month, today),
            "insider sentiment": finnhub_client.stock_insider_sentiment(ticker, last_month, today),
            "earnings_upcoming": earnings_by_ticker.get(ticker),
            "technicals": technicals,
            "sr": sr
        }
    return ticker_to_data


def generate_verdict(ticker, ticker_data):
    trends = ticker_data["trends"]
    insider_sentiment = ticker_data["insider sentiment"]["data"]
    insider_transactions = ticker_data["insider transactions"]["data"]
    earnings_upcoming = ticker_data["earnings_upcoming"]
    technicals = ticker_data["technicals"]
    sr = ticker_data["sr"]

    earnings_context = ""
    if earnings_upcoming:
        earnings_context = f"""
    IMPORTANT - Earnings report due: {earnings_upcoming.get('date')}
    EPS estimate: {earnings_upcoming.get('epsEstimate')}
    Revenue estimate: ${earnings_upcoming.get('revenueEstimate', 0):,.0f}
    Note: Earnings events increase volatility significantly.
    """
    else:
        earnings_context = "No earnings report expected this week."

    system_instruction = f"""You are an experienced stock analyst. Analyse {ticker} and return ONLY valid JSON, no markdown, no explanation. Use double quotes."""

    prompt = f'''
    Analyse {ticker} using the provided data. Be concise and high-signal.
    Focus on confluence between analyst sentiment, insider activity, technicals, risk/reward, and earnings risk.

    Guidelines:
    - Lower forward PE than trailing PE suggests expected earnings growth (bullish)
    - PE >40 requires strong growth to justify. PE 15-30 healthy. PE <15 may indicate undervaluation
    - Negative PE is bearish unless strong turnaround evidence
    - Heavy insider selling is bearish. Weak price action overrides bullish news
    - Oversold does not automatically mean bullish. Low risk/reward (<1.5:1) lowers confidence
    - If signals conflict heavily, choose HOLD

    Latest analyst recommendations: {json.dumps(trends[:1])}
    Insider sentiment (MSPR positive = bullish): {json.dumps(insider_sentiment)}
    Insider transactions: {json.dumps(insider_transactions)}
    Earnings context: {earnings_context}

    Technical indicators:
    RSI: {technicals['rsi']} ({technicals['rsi_signal']})
    MACD: {technicals['macd_signal']} momentum
    Price vs 50-day SMA: {'above' if technicals['above_50sma'] else 'below'}
    Price vs 200-day SMA: {'above' if technicals['above_200sma'] else 'below'}
    Golden cross: {technicals['golden_cross']}
    Bollinger Band position: {technicals['bb_position']} ({technicals['bb_signal']})
    Trailing PE: {technicals['trailingPE']}
    Forward PE: {technicals['forwardPE']}

    Support/Resistance:
    Current price: {sr['current_price']}
    Nearest support: {sr['nearest_support']} ({sr['distance_to_support_pct']}% below)
    Nearest resistance: {sr['nearest_resistance']} ({sr['distance_to_resistance_pct']}% above)
    Risk/reward: {round(sr['distance_to_resistance_pct'] / sr['distance_to_support_pct'], 1) if sr['nearest_support'] and sr['nearest_resistance'] else 'N/A'}:1

    Return this exact JSON:
    {{
        "ticker": "{ticker}",
        "verdict": "buy/hold/sell",
        "confidence": 0.0-1.0,
        "analyst_signal": "bullish/neutral/bearish",
        "insider_signal": "bullish/neutral/bearish",
        "summary": "2-3 sentence plain english summary",
        "key_factors": ["factor1", "factor2", "factor3"]
    }}
    '''

    raw = call_gemini(prompt, system_instruction)

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def generate_all_verdicts(ticker_data):
    verdicts = {}
    for ticker, data in ticker_data.items():
        try:
            verdicts[ticker] = generate_verdict(ticker, data)
            time.sleep(2)
        except Exception as e:
            print(f"Failed for {ticker}: {e}")
    return verdicts


def get_company_profiles(finnhub_client, ticker_list):
    profiles = {}
    for ticker in ticker_list:
        try:
            profile = finnhub_client.company_profile2(symbol=ticker)
            if profile:
                profiles[ticker] = profile
        except Exception as e:
            print(f"Profile failed for {ticker}: {e}")
    return profiles