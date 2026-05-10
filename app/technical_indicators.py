import yfinance as yf
import pandas as pd
from scrape import finnhub_client

def get_technicals(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="3mo")  # 3 months of daily data
    
    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df['Close'].ewm(span=12).mean()
    ema26 = df['Close'].ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['MACD_hist'] = df['MACD'] - df['Signal']
    
    # 50 and 200 day moving averages
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA200'] = df['Close'].rolling(200).mean()
    
    # Bollinger Bands
    sma20 = df['Close'].rolling(20).mean()
    std20 = df['Close'].rolling(20).std()
    df['BB_upper'] = sma20 + (std20 * 2)
    df['BB_lower'] = sma20 - (std20 * 2)
    df['BB_position'] = (df['Close'] - df['BB_lower']) / (df['BB_upper'] - df['BB_lower'])
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "current_price": round(latest['Close'], 2),
        "rsi": round(latest['RSI'], 1),
        "rsi_signal": "overbought" if latest['RSI'] > 70 else "oversold" if latest['RSI'] < 30 else "neutral",
        "macd_hist": round(latest['MACD_hist'], 4),
        "macd_signal": "bullish" if latest['MACD_hist'] > 0 and latest['MACD_hist'] > prev['MACD_hist'] else "bearish",
        "above_50sma": bool(latest['Close'] > latest['SMA50']),
        "above_200sma": bool(latest['Close'] > latest['SMA200']),
        "golden_cross": bool(latest['SMA50'] > latest['SMA200']),
        "bb_position": round(latest['BB_position'], 2),  # 0=bottom of band, 1=top
        "bb_signal": "overbought" if latest['BB_position'] > 0.8 else "oversold" if latest['BB_position'] < 0.2 else "neutral",
        "forwardPE": stock['forwardPE'],
        "trailingPE": stock['trailingPE']
    }


def get_support_resistance(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="6mo")
    
    # recent highs and lows as resistance/support
    # look at 20-day rolling windows
    df['local_max'] = df['High'][(df['High'].shift(1) < df['High']) & 
                                  (df['High'].shift(-1) < df['High'])]
    df['local_min'] = df['Low'][(df['Low'].shift(1) > df['Low']) & 
                                 (df['Low'].shift(-1) > df['Low'])]
    
    current_price = df['Close'].iloc[-1]
    
    # find nearest resistance (above price) and support (below price)
    resistance_levels = df['local_max'].dropna().values
    support_levels = df['local_min'].dropna().values
    
    nearest_resistance = min(
        [r for r in resistance_levels if r > current_price], 
        default=None,
        key=lambda x: x - current_price
    )
    nearest_support = max(
        [s for s in support_levels if s < current_price],
        default=None, 
        key=lambda x: current_price - x
    )
    
    return {
        "current_price": round(current_price, 2),
        "nearest_support": round(nearest_support, 2) if nearest_support else None,
        "nearest_resistance": round(nearest_resistance, 2) if nearest_resistance else None,
        "distance_to_resistance_pct": round(((nearest_resistance - current_price) / current_price) * 100, 1) if nearest_resistance else None,
        "distance_to_support_pct": round(((current_price - nearest_support) / current_price) * 100, 1) if nearest_support else None,
    }