# -*- coding: utf-8 -*-
"""
Created on Sat Apr 26 15:57:21 2025

@author: HOW
"""

import os
import datetime

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
from linebot.models import FollowEvent

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import seaborn as sns
import twstock
import re

# ✅ 載入 .env（本地測試用）
from dotenv import load_dotenv
load_dotenv()

# Line Bot 設定，從環境變數中讀取機密資訊
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET")

# === 安全檢查（防止沒設變數時報錯） ===
if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET :
    raise Exception("❌ 未設定 CHANNEL_ACCESS_TOKEN 或 CHANNEL_SECRET，請檢查環境變數")

#設定seaborn風格
sns.set_theme(style='ticks')

#指定中文字型
font_path = os.path.join('fonts','NotoSansTC-Regular.ttf')
font_prop = fm.FontProperties(fname=font_path)
plt.rcParams['font.family'] = font_prop.get_name()

# 設定字型，避免中文亂碼/避免負號亂碼
#plt.rcParams['font.sans-serif'] = ['Noto Sans TC','Taipei Sans TC Beta', 'SimHei','Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False

# Flask 應用
app = Flask(__name__)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 確保 static 資料夾存在
if not os.path.exists('static'):
    os.makedirs('static')
    
# 警示訂閱設定資料 (key=user_id, value=清單)
alerts = {}
    
# ========== 功能函式區 ==========

# 取得即時股價
def get_stock_price(stock_id):
    stock = twstock.realtime.get(stock_id)
    if stock['success']:
        name = stock['info']['name']
        price = stock['realtime']['latest_trade_price']
        return True,f'{name}({stock_id}) 目前股價:{price}元'
    else:
        return False,f'查無此股票代碼:{stock_id}'

# 畫股價趨勢圖
def plot_stock_trend(stock_id,days=5):
    
    today = datetime.datetime.now()
    start = today - datetime.timedelta(days=days+5)
    
    stock = twstock.Stock(stock_id)
    stock.fetch_from(start.year,start.month)
    
    dates = stock.date[-days:]
    prices = stock.close[-days:]
    
    #找最高與最低
    max_price = max(prices)
    min_price = min(prices)
    max_date = dates[prices.index(max_price)]
    min_date = dates[prices.index(min_price)]
    
    #畫圖
    plt.figure(figsize=(8,4))
    plt.plot(dates,prices,marker="o")
    plt.title(f'{stock_id} 最近{days}日收盤價',fontsize=16,fontproperties=font_prop)
    plt.xlabel('日期',fontsize=12,fontproperties=font_prop)
    plt.ylabel('收盤價(元)',fontsize=12,fontproperties=font_prop)
    plt.grid(True,linestyle='--',alpha=0.7)
    plt.xticks(rotation=45, fontproperties=font_prop)
    plt.yticks(fontproperties=font_prop)
    
    #標記最高點與最低點
    plt.scatter([max_date],[max_price],color='#d62728',s=80,zorder=5,marker='v',label='最高價')
    plt.scatter([min_date],[min_price],color='#1f77b4',s=80,zorder=5,marker='^',label='最低價')
    
    #美化文字
    plt.text(max_date,max_price + 1,f'最高{max_price}',color='#d62728',fontsize=10,
             ha='center',fontproperties=font_prop,bbox=dict(facecolor='white',alpha=0.8,edgecolor='none'))
    plt.text(min_date,min_price - 2,f'最低{min_price}',color='#1f77b4',fontsize=10,
             ha='center',fontproperties=font_prop,bbox=dict(facecolor='white',alpha=0.8,edgecolor='none'))
    
    filename = f'static/{stock_id}_trend.png'
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    
    return filename

# 構建股價文字和圖片網址
def build_stock_reply(stock_id,days=5):
    success, price_text = get_stock_price(stock_id)
    if not success:
        return False, price_text, None

    filename = plot_stock_trend(stock_id,days)
    image_url = f"https://line-bot-stock-9881.onrender.com/{filename}"
    return True, price_text, image_url

def parse_user_input(user_message):
    
    """
    回傳
    {
     'mode':'single' or 'multi',
     'stock_ids':['2330','2317'],
     'days':5 or 30
     }
    """
    parts = user_message.strip().split()
    result = {
        'mode':'single',
        'stock_ids':[],
        'days':5
        }
    
    if parts[0] == '查' and len(parts) > 1 :
        result['mode'] = 'multi'
        result['stock_ids'] = parts[1:]
        
    else:
        result['mode'] = 'single'
        result['stock_ids'] = [parts[0]]
        if len(parts) > 1 :
            keyword = parts[1]
            if keyword in ['30','30天','30日','月線'] :
                result['days'] = 30
                
    return result

# ========== webhook區 ==========
@app.route('/callback',methods=['post'])
def callback():
    signature = request.headers['X-Line-Signature']
    
    body = request.get_data(as_text=True)
    app.logger.info('Request body:' + body)
    
    try:
        handler.handle(body,signature)
    except InvalidSignatureError:
        abort(400)
        
    return 'OK'

# 處理使用者訊息
@handler.add(MessageEvent,message=TextMessage)
def handle_message(event):
    
    # ➤ 判斷是否能抓 user_id（只有 private chat 才行）
    if event.source.type != 'user' :
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='⚠️ 抱歉，目前僅支援私訊（1對1聊天）查詢股票。')
            )
        return
    
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    
    # 價格警示指令處理
    if user_message.startswith('設定 '):
        try:
            match = re.match(r'設定\s+(\d+)\s*([<>])\s*(\d+\.?\d*)',user_message)
            if not match :
                raise ValueError('格式錯誤')
            
            stock_id,operator,target_str = match.groups()
            target_price = float(target_str)
                
            if user_id not in alerts:
                alerts[user_id] = []
                
            alerts[user_id].append({
                'stock_id':stock_id,
                'operator':operator,
                'target':target_price
                })
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f'✅已設定:當{stock_id} {operator} {target_price} 時通知你')
                )
            
        except Exception :
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text='❌設定格式錯誤，請輸入範例:設定 2330 > 800')
                )
        return
    
    parsed = parse_user_input(user_message)
    
    # Step 1:初步回覆提示（reply_message 只能用一次）
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text='正在查詢股票資料，請稍後...')
        )
    
    # Step 2: 使用 push_message 分批主動推送完整資料（不受 5 則限制）
    for stock_id in parsed['stock_ids'] :
        success, price_text, image_url = build_stock_reply(stock_id,parsed['days'])
    
        if not success:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=price_text)
                )
            
        else:
            line_bot_api.push_message(
                user_id,
                [
                    TextSendMessage(text=price_text),
                    ImageSendMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                        )
                    ]
                )
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    welcome_msg = (
        "👋 歡迎加入台灣股市小幫手！\n\n"
        "以下是你可以使用的功能指令：\n"
        "📌 即時股價：輸入股票代碼，如 `2330`\n"
        "📈 趨勢圖：輸入 `2330 30天` 或 `查 2330 2317`(請文字與數字用空白隔開)\n"
        "🔔 價格警示：輸入 `設定 2330 > 800`(請文字與數字、符號用空白隔開)\n"
        "🧾 每 5 分鐘會自動檢查是否達成價格條件\n"
        "💡 圖表會自動標註最高價/最低價\n\n"
        "若要查詢多支股票請用空白分隔，如：`查 2330 2881 2317`\n"
        "🚀 祝你投資順利！"
        )
    line_bot_api.push_message(user_id,TextSendMessage(text=welcome_msg))
            
#推播追蹤價格          
def run_alert_monitor_once():
    #加入日誌輸出來確認 alert_monitor() 有沒有真的跑起來
    print('[INFO] Runing alert monitor ONCE')
    if not alerts:
        print('[INFO] 無警示設定')
        return
        
    for user_id,user_alerts in alerts.items():
        for alert in user_alerts[:]:
            stock_id = alert['stock_id']
            operator = alert['operator']
            target = alert['target']
            
            try:
                stock = twstock.realtime.get(stock_id)
                if stock['success']:
                    current_price = float(stock['realtime']['latest_trade_price'])
                    
                    print(f"[DEBUG] 檢查 {stock_id} 當前價格 {current_price}, 條件 {operator} {target}")
                    #符合條件就推播提醒
                    if (operator == '>' and current_price > target) or \
                        (operator == '<' and current_price < target):
                    
                        msg = f"📈警示觸發:{stock['info']['name']}({stock_id})現在{current_price}元，已{'高於' if operator == '>' else '低於'}{target}元"
                        line_bot_api.push_message(user_id,TextSendMessage(text=msg))
                        
                        #推播後這條件就移除(避免重複通知)
                        user_alerts.remove(alert)
                    
            except Exception as e:
                print(f'[警示錯誤]{stock_id}:{e}')

@app.route("/check_alerts",methods=['GET'])
def check_alerts():
    run_alert_monitor_once()
    return "✅ 價格警示已檢查",200
                    
# ========== 主程式 ==========

if __name__ == "__main__":
    
    app.run()
