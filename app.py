from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import smtplib
from email.mime.text import MIMEText
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    initial_capital = db.Column(db.Float, default=10000)
    stocks = db.relationship('Stock', backref='owner', lazy=True)

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_first_request
def create_tables():
    db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('登入失敗。請檢查電子郵件和密碼', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password)  # 使用默认方法
        user = User(email=email, password=hashed_password)
        db.session.add(user)
        db.session.commit()
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
        initial_capital = float(request.form['initial_capital'])
        current_user.initial_capital = initial_capital
        # 清空已購買的股票
        current_user.stocks = []
        db.session.commit()
        flash('初始資金已更新並且已清空所有已購買的股票！', 'success')
        return redirect(url_for('dashboard'))
    return render_template('settings.html')

@app.route('/stock_search', methods=['GET', 'POST'])
@login_required
def stock_search():
    stock_data = None
    if request.method == 'POST':
        stock_symbol = request.form['stock_symbol']
        # 確保輸入的是數字代碼或字母代碼
        if stock_symbol.isdigit() or stock_symbol.isalpha():
            response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
            if response.status_code == 200:
                stock_data = response.json()
                if 'c' not in stock_data:  # Check if the stock symbol is valid
                    flash('無效的股票代碼，請重新輸入。', 'danger')
                    stock_data = None
            else:
                flash('搜尋失敗，請稍後再試。', 'danger')
        else:
            flash('股票代碼必須是字母或數字。', 'danger')
    return render_template('stock_search.html', stock_data=stock_data)

@app.route('/buy_stock', methods=['POST'])
@login_required
def buy_stock():
    stock_symbol = request.form['stock_symbol']
    quantity = int(request.form['quantity'])
    
    # 查詢股價
    response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
    stock_price = response.json().get('c', 0)
    
    if current_user.initial_capital >= stock_price * quantity:
        # 更新用戶的初始資金
        current_user.initial_capital -= stock_price * quantity
        # 儲存已購買股票
        stock = Stock(symbol=stock_symbol, quantity=quantity, owner=current_user)
        db.session.add(stock)
        db.session.commit()
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
    stocks = Stock.query.filter_by(owner=current_user).all()

    if request.method == 'POST':
        total_profit = 0
        for stock in stocks:
            stock_symbol = stock.symbol
            quantity = stock.quantity

            # 查詢最新股價
            response = requests.get(f'https://finnhub.io/api/v1/quote?symbol={stock_symbol}&token={Config.FINNHUB_API_KEY}')
            stock_price = response.json().get('c', 0)
            total_profit += (stock_price - (stock_price * 0.9)) * quantity  # 假設購買價格是當前股價的90%
        
        # 更新用戶初始資金
        current_user.initial_capital += total_profit
        # 清空用戶的股票
        for stock in stocks:
            db.session.delete(stock)
        db.session.commit()
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
