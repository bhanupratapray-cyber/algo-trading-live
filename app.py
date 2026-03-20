from flask import Flask, render_template, request
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import sqlite3
import warnings
import os

warnings.filterwarnings('ignore')

app = Flask(__name__)
analyzer = SentimentIntensityAnalyzer()

@app.route('/', methods=['GET', 'POST'])
def home():
    # 1. READ DATABASE
    top_picks = []
    last_updated = "No Data Yet"
    try:
        # Dynamically find the database file in the current folder
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(BASE_DIR, 'market_data.db')
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ticker, price, rsi, ma_40, ma_50, ema_20, pivot, verdict, scan_date FROM top_picks")
        top_picks = cursor.fetchall() 
        if len(top_picks) > 0: 
            last_updated = top_picks[0][8] # Scan Date is now the 8th item in the list
        conn.close()
    except Exception as e:
        pass

    # 2. DEFAULT SETTINGS
    tickers = ["TCS.NS", "INFY.NS", "SUNPHARMA.NS", "CIPLA.NS", "RELIANCE.NS"]
    ema_period = 20 
    
    # Default checkboxes to be checked if you just load the page
    active_criteria = ['ma50', 'rsi', 'news'] 
    
    if request.method == 'POST':
        user_ticker = request.form.get('ticker').upper()
        if not user_ticker.endswith('.NS'): user_ticker += '.NS'
        tickers = [user_ticker]
        
        user_ema = request.form.get('ema_period')
        if user_ema and user_ema.isdigit():
            ema_period = int(user_ema)
            
        # Get the list of checkboxes the user clicked
        active_criteria = request.form.getlist('criteria')

    scan_results = []
    
    # 3. THE ON-DEMAND ENGINE
    for stock_name in tickers:
        try:
            stock = yf.Ticker(stock_name)
            stock_data = stock.history(period="1y")
            if len(stock_data) < 2: continue 
                
            stock_data['50_MA'] = stock_data['Close'].rolling(window=50).mean()
            stock_data['40_MA'] = stock_data['Close'].rolling(window=40).mean()
            stock_data['EMA'] = stock_data['Close'].ewm(span=ema_period, adjust=False).mean()
            
            delta = stock_data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            stock_data['RSI'] = 100 - (100 / (1 + rs))
            
            latest_close = float(stock_data.iloc[-1]['Close'])
            latest_ma = float(stock_data.iloc[-1]['50_MA'])
            latest_40_ma = float(stock_data.iloc[-1]['40_MA'])
            latest_ema = float(stock_data.iloc[-1]['EMA']) 
            latest_rsi = float(stock_data.iloc[-1]['RSI'])
            
            prev_high = float(stock_data.iloc[-2]['High'])
            prev_low = float(stock_data.iloc[-2]['Low'])
            prev_close = float(stock_data.iloc[-2]['Close'])
            pivot = (prev_high + prev_low + prev_close) / 3
            r1 = (pivot * 2) - prev_low
            s1 = (pivot * 2) - prev_high
            
            avg_gain = round(float(gain.iloc[-1]), 2)
            avg_loss = round(float(loss.iloc[-1]), 2)
            rs_value = round(float(rs.iloc[-1]), 2) 
            
            # --- THE NEWS ENGINE ---
            news_list = stock.news
            total_score, article_count = 0, 0
            news_details = [] 
            
            for article in news_list:
                if 'title' in article: headline = article['title']
                elif 'content' in article and 'title' in article['content']: headline = article['content']['title']
                else: continue
                
                score = analyzer.polarity_scores(headline)['compound']
                total_score += score
                article_count += 1
                
                if score >= 0.05: mood = "🟢 POSITIVE"
                elif score <= -0.05: mood = "🔴 NEGATIVE"
                else: mood = "⚪ NEUTRAL"
                news_details.append(f"{mood} (Score: {score:.2f}) | {headline}")
                
            news_signal = "NEUTRAL"
            avg_score = 0
            if article_count > 0:
                avg_score = round(total_score / article_count, 2)
                if avg_score >= 0.05: news_signal = "POSITIVE"
                elif avg_score <= -0.05: news_signal = "NEGATIVE"

            # --- THE NEW DYNAMIC VERDICT LOGIC ---
            buy_met = True
            oversold_met = True
            has_math = False
            
            # 1. Check only what the user selected
            if 'ma50' in active_criteria:
                has_math = True
                if latest_close <= latest_ma: buy_met = False
                if latest_close >= latest_ma: oversold_met = False
            if 'ema' in active_criteria:
                has_math = True
                if latest_close <= latest_ema: buy_met = False
                if latest_close >= latest_ema: oversold_met = False
            if 'pivot' in active_criteria:
                has_math = True
                if latest_close <= pivot: buy_met = False
                if latest_close >= pivot: oversold_met = False
            if 'rsi' in active_criteria:
                has_math = True
                if latest_rsi >= 70: buy_met = False
                if latest_rsi >= 30: oversold_met = False
                
            math_signal = "WAIT"
            if has_math:
                if buy_met: math_signal = "BUY"
                elif oversold_met: math_signal = "OVERSOLD"
                
            # 2. Combine Math with News based on checkboxes
            verdict = "🟡 NO ACTION"
            if not active_criteria:
                verdict = "⚪ NO CRITERIA SELECTED"
            elif 'news' in active_criteria:
                if math_signal == "BUY" and news_signal == "POSITIVE": verdict = "🔥 STRONG CONVICTION BUY"
                elif math_signal == "OVERSOLD" and news_signal == "POSITIVE": verdict = "💡 POTENTIAL REVERSAL"
                elif math_signal in ["BUY", "OVERSOLD"] and news_signal == "NEGATIVE": verdict = "⚠️ CAUTION (Bad News)"
                elif not has_math and news_signal == "POSITIVE": verdict = "🟢 BUY (News Only)"
                elif not has_math and news_signal == "NEGATIVE": verdict = "🔴 SELL (News Only)"
            else:
                # If they didn't check News, just output the math result
                if math_signal == "BUY": verdict = "🟢 BUY (Math Only)"
                elif math_signal == "OVERSOLD": verdict = "💡 OVERSOLD (Math Only)"
            
            scan_results.append({
                "ticker": stock_name, "price": round(latest_close, 2), "rsi": round(latest_rsi, 2),
                "ma_40": round(latest_40_ma, 2), "ma_50": round(latest_ma, 2), "ema_val": round(latest_ema, 2), 
                "pivot": round(pivot, 2), "r1": round(r1, 2), "s1": round(s1, 2),
                "prev_high": round(prev_high, 2), "prev_low": round(prev_low, 2), "prev_close": round(prev_close, 2),
                "math": math_signal, "news": news_signal, "news_details": news_details, "avg_news_score": avg_score,
                "avg_gain": avg_gain, "avg_loss": avg_loss, "rs_value": rs_value, "verdict": verdict
            })
        except Exception as e:
            pass

    return render_template('index.html', results=scan_results, top_picks=top_picks, last_updated=last_updated, current_ema=ema_period, active_criteria=active_criteria)

if __name__ == '__main__':
    app.run(debug=True)
