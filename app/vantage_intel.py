import requests
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv

# replace the "demo" apikey below with your own key from https://www.alphavantage.co/support/#api-key
alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY")
three_days_ago = datetime.now() - timedelta(days=3)


date = three_days_ago.strftime("%Y%m%d")
formatted = f"{date}T0000"

url = f'https://www.alphavantage.co/query?function=NEWS_SENTIMENT&time_from={formatted}&limit=20&apikey={alpha_vantage_key}'

r = requests.get(url)
data = r.json()

def extract_av_tickers(av_data=data, min_relevance=0.5, min_mentions=2):
    ticker_scores = {}
    
    for article in av_data.get("feed", []):
        for ticker_sentiment in article.get("ticker_sentiment", []):
            ticker = ticker_sentiment["ticker"]
            relevance = float(ticker_sentiment["relevance_score"])
            score = float(ticker_sentiment["ticker_sentiment_score"])
            
            # skip low relevance mentions — ticker just appeared in passing
            if relevance < min_relevance:
                continue
            
            # skip ETFs and funds — too many obscure ones pollute results
            if len(ticker) > 5 or "." in ticker:
                continue
                
            if ticker not in ticker_scores:
                ticker_scores[ticker] = {
                    "mentions": 0,
                    "scores": [],
                    "labels": []
                }
            
            ticker_scores[ticker]["mentions"] += 1
            ticker_scores[ticker]["scores"].append(score)
            ticker_scores[ticker]["labels"].append(
                ticker_sentiment["ticker_sentiment_label"]
            )
    
    # build final list
    results = []
    for ticker, data in ticker_scores.items():
        if data["mentions"] < min_mentions:
            continue
        
        avg_score = sum(data["scores"]) / len(data["scores"])
        
        # most common label
        from collections import Counter
        dominant_label = Counter(data["labels"]).most_common(1)[0][0]
        
        results.append({
            "ticker": ticker,
            "mentions": data["mentions"],
            "avg_sentiment_score": round(avg_score, 4),
            "sentiment_label": dominant_label,
            "signal": "bullish" if avg_score >= 0.15 
                      else "bearish" if avg_score <= -0.15 
                      else "neutral"
        })
    
    # sort by mentions then sentiment strength
    results.sort(key=lambda x: (x["mentions"], abs(x["avg_sentiment_score"])), reverse=True)
    
    return results[:15]  # top 15