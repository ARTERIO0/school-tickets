import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
# Секретный ключ нужен для работы сессий (чтобы сайт помнил, что ты вошел)
app.secret_key = 'school_tickets_secret_key_12345' 

DB_NAME = 'tickets.db'

# ПАРОЛЬ ДЛЯ ВХОДА В АДМИНКУ (можешь поменять на свой)
ADMIN_PASSWORD = 'admin123'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tickets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room TEXT NOT NULL,
                  issue TEXT NOT NULL,
                  author TEXT,
                  status TEXT DEFAULT 'Новая',
                  created_at TEXT)''')
    conn.commit()
    conn.close()

# Декоратор: пускает только авторизованных
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'Неверный пароль'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM tickets ORDER BY id DESC")
    tickets = c.fetchall()
    conn.close()
    return render_template('index.html', tickets=tickets)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        room = request.form['room']
        issue = request.form['issue']
        author = request.form.get('author', 'Аноним')
        created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO tickets (room, issue, author, created_at) VALUES (?, ?, ?, ?)",
                  (room, issue, author, created_at))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/resolve/<int:ticket_id>')
@login_required  # <--- Защита: только для админа
def resolve(ticket_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'Выполнено' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# Создаем базу при запуске (для Gunicorn)
init_db()

if __name__ == '__main__':
    app.run(debug=True)
