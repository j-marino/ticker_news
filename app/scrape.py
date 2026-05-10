import finnhub
import http.client, urllib.parse
import os
import json

from collections import Counter
from dotenv import load_dotenv
from datetime import date, timedelta
from ollama import chat
from ollama import ChatResponse
from technical_indicators import get_technicals, get_support_resistance
from vantage_intel import extract_av_tickers

load_dotenv()

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
            e['revenueEstimate'] > 670_000_000):  # $670M+ revenue companies only
            tickers.append(e['symbol'])
    
    return tickers

def get_final_watchlist(finnhub_client):
    # existing sources
    news_tickers = [t[0] for t in extract_trending_tickers(parsed)]
    earnings_tickers = get_quality_earnings_tickers(finnhub_client)
    
    # alpha vantage source
    av_tickers = [t["ticker"] for t in extract_av_tickers()]
    
    merged = list(set(news_tickers + earnings_tickers + av_tickers))
    return merged[:16] # cap at n num of tickers

def get_recommendation_data(finnhub_client):
    ticker_list = get_final_watchlist(finnhub_client)
    today = date.today().strftime('%Y-%m-%d')
    last_month = (date.today() - timedelta(days=31)).strftime('%Y-%m-%d')
    next_week = (date.today() + timedelta(days=7)).strftime('%Y-%m-%d')
    
    # get full earnings calendar once
    earnings_calendar = finnhub_client.earnings_calendar(
        _from=today, to=next_week, symbol="", international=False
    ).get('earningsCalendar', [])
    
    # map ticker -> earnings date
    earnings_by_ticker = {e['symbol']: e for e in earnings_calendar}
    
    ticker_to_data = {}

    for ticker in ticker_list:
        try:
            technicals = get_technicals(ticker)
            sr = get_support_resistance(ticker)
        except Exception:
            technicals = None
            continue # do not add if there are no technicals or support/resistance
    
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
    Note: Earnings events increase volatility significantly. Factor this into confidence and verdict.
    """
    else:
        earnings_context = "No earnings report expected this week."

    context = f"""
    You are an experienced stock analyst.

    Analyse {ticker} using the provided data and determine:
    - BUY
    - HOLD
    - SELL

    Be concise and high-signal.
    Avoid generic AI wording.
    Focus on confluence between:
    - analyst sentiment
    - insider activity
    - technicals
    - risk/reward
    - earnings risk

    Important:
    - Refer back to and reference technicals in thesis
    - Lower forward PE than trailing PE suggests expected earnings growth (bullish).
    - Extremely high PE ratios (>40) require strong growth to justify valuation.
    - PE between 15-30 is generally healthy for established growth companies.
    - PE below 15 may indicate undervaluation OR market pessimism.
    - Negative PE is bearish unless strong turnaround evidence exists.
    - Falling forward PE with strong technicals increases bullish conviction.
    - High PE combined with insider selling or weak momentum is bearish.
    - Do not treat valuation alone as a buy/sell signal.
    - Weak price action overrides bullish news.
    - Heavy insider selling is bearish.
    - Oversold does not automatically mean bullish.
    - Low risk/reward (<1.5:1) lowers confidence.
    - If signals conflict heavily, say that there is too much uncertainty (OR WORDS TO THAT EFFECT) and choose HOLD.
    """

    prompt = f'''
    {context}
    Latest analyst recommendations:
    {json.dumps(trends[:1])}

    Insider sentiment (MSPR = insider buying pressure, positive = bullish):
    {json.dumps(insider_sentiment)}

    Insider transactions:
    {json.dumps(insider_transactions)}

    Earnings context:
    {earnings_context}

    Technical indicators {ticker}:
    RSI: {technicals['rsi']} ({technicals['rsi_signal']})
    MACD: {technicals['macd_signal']} momentum
    Price vs 50-day SMA: {'above' if technicals['above_50sma'] else 'below'}
    Price vs 200-day SMA: {'above' if technicals['above_200sma'] else 'below'}  
    Golden cross active: {technicals['golden_cross']}
    Bollinger Band position: {technicals['bb_position']} ({technicals['bb_signal']})
    Trailing PE: {technicals['trailingPE']}
    Forward PE: {technicals['forwardPE']}

    Support/Resistance context:
    Current price: {sr['current_price']}
    Nearest support: {sr['nearest_support']} ({sr['distance_to_support_pct']}% below)
    Nearest resistance: {sr['nearest_resistance']} ({sr['distance_to_resistance_pct']}% above)
    Risk/reward ratio: {round(sr['distance_to_resistance_pct'] / sr['distance_to_support_pct'], 1) if sr['nearest_support'] and sr['nearest_resistance'] else 'N/A'}:1

    Factor the risk/reward into confidence. Below 1.5:1 should reduce confidence significantly.

    Return this exact JSON:
    {{
        "ticker": "{ticker}",
        "verdict": "buy/hold/sell",
        "confidence": 0.0-1.0,
        "analyst_signal": "bullish/neutral/bearish",
        "insider_signal": "bullish/neutral/bearish",
        "summary": "2-3 sentence plain english summary of the overall picture",
        "key_factors": ["factor1", "factor2", "factor3"]
    }}
    '''

    response: ChatResponse = chat(model=model, format='json',messages=[
    {
        'role': 'user',
        'content': prompt,
    },
    ])


    # AI returns ``` at JSON start since its a messageResponse object instead of a JSON, despite the fact i literally said what i want.... FUCK SAKE
    raw = response.message.content.strip()
    if not raw:
        raise ValueError(f"Empty response from LOCAL AI for {ticker}")

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    
    
    return json.loads(raw)

def generate_all_verdicts(ticker_data):
    verdicts = {}
    for ticker, data in ticker_data.items():
        try:
            verdicts[ticker] = generate_verdict(ticker, data)
        except Exception as e:
            print(f"Failed for {ticker}: {e}")
    return verdicts

import yfinance as yf

def get_company_description(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get("longBusinessSummary")
    except:
        return None

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

conn = http.client.HTTPSConnection('api.marketaux.com')
params = urllib.parse.urlencode({
    'api_token': os.getenv("MARKETAUX_API_KEY"),
    'industries': 'Technology',
    'countries': 'us,uk',
    'sentiment_gte': -1,  # all sentiment
    'limit': 100, 
    'language': 'en'
}) 


conn.request('GET', '/v1/news/all?{}'.format(params))

res = conn.getresponse()
data = res.read()
parsed = json.loads(data.decode('utf-8'))


# Setup client
finnhub_client = finnhub.Client(api_key=os.getenv("FINN_API_KEY"))

model = 'phi4-mini:3.8b'


# all the allowed info from the FINN API within the FREE SECTOR
"""
# Basic financials ***
print(finnhub_client.company_basic_financials('AAPL', 'all'))

# Earnings surprises ***
print(finnhub_client.company_earnings('TSLA', limit=5))

# Company News **
# Need to use _from instead of from to avoid conflict
print(finnhub_client.company_news('AAPL', _from="2020-06-01", to="2020-06-10"))

# Company Peers
print(finnhub_client.company_peers('AAPL'))

# Company Profile 2
print(finnhub_client.company_profile2(symbol='AAPL'))

# Crypto Exchange
print(finnhub_client.crypto_exchanges())

# Crypto symbols
print(finnhub_client.crypto_symbols('BINANCE'))

# Filings
print(finnhub_client.filings(symbol='AAPL', _from="2020-01-01", to="2020-06-11"))

# Financials as reported
print(finnhub_client.financials_reported(symbol='AAPL', freq='annual'))

# IPO calendar
print(finnhub_client.ipo_calendar(_from="2020-05-01", to="2020-06-01"))

# Recommendation trends ** big **
print(finnhub_client.recommendation_trends('AAPL'))

# Earnings Calendar
print(finnhub_client.earnings_calendar(_from="2020-06-10", to="2020-06-30", symbol="", international=False))

# Symbol lookup
print(finnhub_client.symbol_lookup('apple'))

# Insider transactions ** big **
print(finnhub_client.stock_insider_transactions('AAPL', '2021-01-01', '2021-03-01'))

# Insider sentiment
print(finnhub_client.stock_insider_sentiment('AAPL', '2021-01-01', '2022-03-01'))

# Lobbying
print(finnhub_client.stock_lobbying("AAPL", "2021-01-01", "2022-06-15"))

## Market Holday / Status
print(finnhub_client.market_holiday(exchange='US'))
print(finnhub_client.market_status(exchange='US'))
"""