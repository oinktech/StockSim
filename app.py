from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import smtplib
from email.mime.text import MIMEText
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# 初始化 PyMongo
mongo = PyMongo(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    pass

@login_manager.user_loader
def load_user(user_id):
    user = mongo.db.users.find_one({"_id": user_id})
    if user:
        user_obj = User()
        user_obj.id = user['_id']
        return user_obj
    return None

@app.before_first_request
def init_db():
    """ 初始化数据库和插入默认数据 """
    if mongo.db.users.count_documents({}) == 0:  # 检查是否存在用户
        mongo.db.users.insert_one({
            "email": "admin@example.com",
            "password": generate_password_hash("admin123"),
            "initial_capital": 10000,
            "stocks": []
        })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = mongo.db.users.find_one({"email": email})
        if user and check_password_hash(user['password'], password):
            user_obj = User()
            user_obj.id = user['_id']
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        flash('登入失敗。請檢查電子郵件和密碼', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password)
        mongo.db.users.insert_one({"email": email, "password": hashed_password, "initial_capital": 10000, "stocks": []})
        flash('註冊成功！您現在可以登入。', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        initial_capital = request.form['initial_capital']
        mongo.db.users.update_one({"_id": current_user.id}, {"$set": {"initial_capital": initial_capital}})
        # 清空已購買的股票
        mongo.db.users.update_one({"_id": current_user.id}, {"$set": {"stocks": []}})
        flash('初始資金已更新並且已清空所有已購買的股票！', 'success')
        return redirect(url_for('dashboard'))
    return render_template('settings.html')

@app.route('/stock_search', methods=['GET', 'POST'])
@login_required
def stock_search():
    stock_data = None
    if request.method == 'POST':
        stock_symbol = request.form['stock_symbol']
        response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
        if response.status_code == 200:
            stock_data = response.json()
            if 'c' not in stock_data:  # Check if the stock symbol is valid
                flash('無效的股票代碼，請重新輸入。', 'danger')
                stock_data = None
        else:
            flash('搜尋失敗，請稍後再試。', 'danger')
    return render_template('stock_search.html', stock_data=stock_data)

@app.route('/buy_stock', methods=['POST'])
@login_required
def buy_stock():
    stock_symbol = request.form['stock_symbol']
    quantity = int(request.form['quantity'])
    user = mongo.db.users.find_one({"_id": current_user.id})
    
    # 查詢股價
    response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
    stock_price = response.json().get('c', 0)
    
    if user['initial_capital'] >= stock_price * quantity:
        # 更新用戶的初始資金
        mongo.db.users.update_one({"_id": current_user.id}, {"$set": {"initial_capital": user['initial_capital'] - stock_price * quantity}})
        # 儲存已購買股票
        mongo.db.users.update_one({"_id": current_user.id}, {"$push": {"stocks": {"symbol": stock_symbol, "quantity": quantity}}})
        # 發送郵件通知
        send_email_notification(stock_symbol, quantity)
        flash('成功購買股票！', 'success')
    else:
        flash('資金不足！', 'danger')
    return redirect(url_for('portfolio'))

def send_email_notification(stock_symbol, quantity):
    msg = MIMEText(f'您已購買 {quantity} 股 {stock_symbol}.')
    msg['Subject'] = '股票購買確認'
    msg['From'] = Config.GMAIL_USER
    msg['To'] = Config.GMAIL_USER

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(Config.GMAIL_USER, Config.GMAIL_PASSWORD)
        server.send_message(msg)

@app.route('/portfolio', methods=['GET', 'POST'])
@login_required
def portfolio():
    user = mongo.db.users.find_one({"_id": current_user.id})
    stocks = user.get('stocks', [])

    if request.method == 'POST':
        total_profit = 0
        for stock in stocks:
            stock_symbol = stock['symbol']
            quantity = stock['quantity']

            # 查詢最新股價
            response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
            stock_price = response.json().get('c', 0)
            total_profit += (stock_price - (stock_price * 0.9)) * quantity  # 假設購買價格是當前股價的90%
        
        # 更新用戶初始資金
        mongo.db.users.update_one({"_id": current_user.id}, {"$set": {"initial_capital": user['initial_capital'] + total_profit}})
        # 清空用戶的股票
        mongo.db.users.update_one({"_id": current_user.id}, {"$set": {"stocks": []}})
        flash(f'所有股票已成功賣出，總利潤為: {total_profit:.2f} 元', 'success')
        return redirect(url_for('portfolio'))

    return render_template('portfolio.html', stocks=stocks)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
