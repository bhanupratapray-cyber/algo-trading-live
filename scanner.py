import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import sqlite3
import datetime
import warnings
import time
import os

warnings.filterwarnings('ignore')

print("⚙️ Waking up Background Scanner...")

# Force the database to save exactly where this Python script lives
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'market_data.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. UPGRADE THE DATABASE STRUCTURE
cursor.execute('DROP TABLE IF EXISTS top_picks')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS top_picks (
        ticker TEXT,
        price REAL,
        rsi REAL,
        ma_40 REAL,
        ma_50 REAL, 
        ema_20 REAL, 
        pivot REAL,  
        verdict TEXT,
        scan_date TEXT
    )
''')
conn.commit()

tickers = ["TCS.NS", "INFY.NS", "SUNPHARMA.NS", "CIPLA.NS", "RELIANCE.NS", 
           "ITBEES.NS", "SBIN.NS", "HDFCBANK.NS", "ZOMATO.NS", "ITC.NS"]

analyzer = SentimentIntensityAnalyzer()
today = datetime.datetime.now().strftime("%Y-%m-%d")

print(f"📊 Scanning {len(tickers)} stocks. Looking for top setups...\n")

for stock_name in tickers:
    try:
        stock = yf.Ticker(stock_name)
        stock_data = stock.history(period="1y")
        
        if len(stock_data) < 2: continue
            
        # --- THE 6 INDICATORS MATH ---
        stock_data['50_MA'] = stock_data['Close'].rolling(window=50).mean()
        stock_data['40_MA'] = stock_data['Close'].rolling(window=40).mean()
        stock_data['EMA_20'] = stock_data['Close'].ewm(span=20, adjust=False).mean()
        
        delta = stock_data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        stock_data['RSI'] = 100 - (100 / (1 + rs))
        
        latest_close = float(stock_data.iloc[-1]['Close'])
        latest_ma = float(stock_data.iloc[-1]['50_MA'])
        latest_40_ma = float(stock_data.iloc[-1]['40_MA'])
        latest_ema = float(stock_data.iloc[-1]['EMA_20'])
        latest_rsi = float(stock_data.iloc[-1]['RSI'])
        
        prev_high = float(stock_data.iloc[-2]['High'])
        prev_low = float(stock_data.iloc[-2]['Low'])
        prev_close = float(stock_data.iloc[-2]['Close'])
        pivot = (prev_high + prev_low + prev_close) / 3
        
        # --- BACKGROUND MASTER STRATEGY ---
        # It must be above the 50 MA AND above the 20 EMA to trigger a Buy!
        math_signal = "WAIT"
        if latest_close > latest_ma and latest_close > latest_ema and latest_rsi < 70: 
            math_signal = "BUY"
        elif latest_rsi < 30: 
            math_signal = "OVERSOLD"

        news_list = stock.news
        total_score, article_count = 0, 0
        
        for article in news_list:
            if 'title' in article: headline = article['title']
            elif 'content' in article and 'title' in article['content']: headline = article['content']['title']
            else: continue
            total_score += analyzer.polarity_scores(headline)['compound']
            article_count += 1
            
        news_signal = "NEUTRAL"
        if article_count > 0:
            avg_score = total_score / article_count
            if avg_score >= 0.05: news_signal = "POSITIVE"
            elif avg_score <= -0.05: news_signal = "NEGATIVE"
                
        verdict = "🟡 NO ACTION"
        if math_signal == "BUY" and news_signal == "POSITIVE": verdict = "🔥 STRONG BUY"
        elif math_signal == "OVERSOLD" and news_signal == "POSITIVE": verdict = "💡 POTENTIAL REVERSAL"
        elif math_signal == "BUY" and news_signal == "NEGATIVE": verdict = "⚠️ CAUTION"
        
        if verdict in ["🔥 STRONG BUY", "💡 POTENTIAL REVERSAL", "⚠️ CAUTION"]:
            print(f"✅ Found Setup: {stock_name} -> {verdict}")
            cursor.execute('''
                INSERT INTO top_picks (ticker, price, rsi, ma_40, ma_50, ema_20, pivot, verdict, scan_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (stock_name, round(latest_close, 2), round(latest_rsi, 2), round(latest_40_ma, 2), 
                  round(latest_ma, 2), round(latest_ema, 2), round(pivot, 2), verdict, today))
            conn.commit()
            
    except Exception as e:
        pass
    time.sleep(2)

conn.close()
print("\n✅ Background Scan Complete. Upgraded database saved.")
