import sqlite3
import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory

from pywebpush import webpush, WebPushException

app = Flask(__name__)
app.secret_key = 'school_tickets_secret_key_12345'

DB_NAME = 'tickets.db'
ADMIN_PASSWORD = 'admin123'  # Поменяй на свой пароль!

VAPID_PUBLIC_KEY = "BFAWX562uiK0qzyL-U08CcqdJP3odtYP8hLapr8qn5N1l1R10sMUjMsT9hpqawt0eq0UwcxFPDyOZGXt8UXXy"

VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg1Zdpom9N8tzyUWA
RrDCzC6P8V3ru1LyY+O6ADu0BQRANCAwVgf+etropNQcS8i1/IPNhKHST9Hb
WD/1S2qa/Kp+tdSJYKdLDF1PrE/YaamsLQhqj1MHFxT3CjmR17FF8W
-----END PRIVATE KEY-----"""

VAPID_CLAIMS = {"sub": "mailto:your_email@example.com"}


@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tickets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room TEXT NOT NULL,
                  issue TEXT NOT NULL,
                  author TEXT,
                  status TEXT DEFAULT 'Новая',
                  created_at TEXT,
                  priority TEXT DEFAULT 'Обычная')''')
    # Миграции: добавляем новые колонки, если их ещё нет
    for col, col_def in [('category', "TEXT DEFAULT '📝 Другое'"), ('comment', 'TEXT')]:
        try:
            c.execute(f"ALTER TABLE tickets ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # колонка уже существует
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  endpoint TEXT UNIQUE NOT NULL,
                  p256dh TEXT NOT NULL,
                  auth TEXT NOT NULL)''')
    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def send_push_notification(title, body):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT endpoint, p256dh, auth FROM subscriptions")
    subs = c.fetchall()
    conn.close()
    for sub in subs:
        sub_info = {"endpoint": sub[0], "keys": {"p256dh": sub[1], "auth": sub[2]}}
        try:
            webpush(
                subscription_info=sub_info,
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as e:
            if e.response and e.response.status_code in [404, 410]:
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("DELETE FROM subscriptions WHERE endpoint = ?", (sub[0],))
                conn.commit()
                conn.close()


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
    c.execute("""SELECT id, room, issue, author, status, created_at, priority, category, comment
                 FROM tickets
                 ORDER BY CASE WHEN priority = 'Срочная' THEN 0 ELSE 1 END, id DESC""")
    tickets = c.fetchall()
    conn.close()
    return render_template('index.html', tickets=tickets, vapid_public_key=VAPID_PUBLIC_KEY)


@app.route('/api/tickets')
def api_tickets():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""SELECT id, room, issue, author, status, created_at, priority, category, comment
                 FROM tickets
                 ORDER BY CASE WHEN priority = 'Срочная' THEN 0 ELSE 1 END, id DESC""")
    tickets = c.fetchall()
    conn.close()
    return jsonify([{
        'id': t[0], 'room': t[1], 'issue': t[2], 'author': t[3],
        'status': t[4], 'created_at': t[5], 'priority': t[6],
        'category': t[7], 'comment': t[8]
    } for t in tickets])


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        room = request.form['room']
        issue = request.form['issue']
        author = request.form.get('author', 'Аноним')
        priority = request.form.get('priority', 'Обычная')
        category = request.form.get('category', '📝 Другое')
        created_at = datetime.now().strftime("%d.%m.%Y %H:%M")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""INSERT INTO tickets (room, issue, author, created_at, priority, category)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (room, issue, author, created_at, priority, category))
        conn.commit()
        conn.close()

        send_push_notification(
            title=f"Новая заявка: каб. {room}",
            body=f"{category}: {issue[:40]}{'...' if len(issue) > 40 else ''}"
        )
        return redirect(url_for('index'))
    return render_template('add.html')


@app.route('/progress/<int:ticket_id>')
@login_required
def progress(ticket_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'В работе' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/resolve/<int:ticket_id>')
@login_required
def resolve(ticket_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'Выполнено' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/delete/<int:ticket_id>')
@login_required
def delete_ticket(ticket_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/comment/<int:ticket_id>', methods=['POST'])
@login_required
def add_comment(ticket_id):
    comment_text = request.form.get('comment', '').strip()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tickets SET comment = ? WHERE id = ?", (comment_text, ticket_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))


@app.route('/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error"}), 400
    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not endpoint or not p256dh or not auth:
        return jsonify({"status": "error"}), 400
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO subscriptions (endpoint, p256dh, auth) VALUES (?, ?, ?)",
                  (endpoint, p256dh, auth))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


init_db()

if __name__ == '__main__':
    app.run(debug=True)
