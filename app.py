import os
import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from pywebpush import webpush, WebPushException

app = Flask(__name__)
app.secret_key = 'school_tickets_secret_key_12345'

# --- НАСТРОЙКА БАЗЫ ДАННЫХ ---
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///tickets.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
if DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ADMIN_PASSWORD = 'admin123'  # Поменяй на свой пароль!

VAPID_PUBLIC_KEY = "BOOk-J5TstzjT2OUNrELa7ka1FNcHq4o7WKESG7E-SVTVzd5j_PxrP16p6oHvOBsLrILMyxWXsAz8pPn3sA_cuM"

VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgC73bi4J3aPnSmsV2
N5gN0edw6v8a8XwFskI/rmBQaIKhRANCAATjpPieU7Lc409jlDaxC2u5GtRTXB6u
KO1ihEhuxPklU1c3eY/z8az9eqeqB7zgbC6yCzMsVl7AM/KT597AP3Lj
-----END PRIVATE KEY-----"""

VAPID_CLAIMS = {"sub": "mailto:your_email@example.com"}


# --- МОДЕЛИ БАЗЫ ДАННЫХ ---
class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), nullable=False)
    issue = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100))
    status = db.Column(db.String(20), default='Новая')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    priority = db.Column(db.String(20), default='Обычная')
    category = db.Column(db.String(50), default='📝 Другое')
    comment = db.Column(db.Text)


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.Text, unique=True, nullable=False)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)


@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def send_push_notification(title, body):
    try:
        subs = Subscription.query.all()
        for sub in subs:
            sub_info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
            try:
                webpush(
                    subscription_info=sub_info,
                    data=json.dumps({"title": title, "body": body}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS
                )
            except WebPushException as e:
                print(f"WebPush ошибка для {sub.endpoint[:30]}: {e}")
                if e.response and e.response.status_code in [404, 410]:
                    db.session.delete(sub)
                    db.session.commit()
            except Exception as e:
                print(f"Неизвестная ошибка push: {e}")
    except Exception as e:
        # Самое главное: push не должен ломать создание заявки!
        print(f"Критическая ошибка в send_push_notification: {e}")


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
    tickets = Ticket.query.order_by(Ticket.priority.desc(), Ticket.id.desc()).all()
    return render_template('index.html', tickets=tickets, vapid_public_key=VAPID_PUBLIC_KEY)


@app.route('/report')
def report():
    tickets = Ticket.query.order_by(Ticket.priority.desc(), Ticket.id.desc()).all()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return render_template('report.html', tickets=tickets, now=now)


@app.route('/api/tickets')
def api_tickets():
    tickets = Ticket.query.order_by(Ticket.priority.desc(), Ticket.id.desc()).all()
    return jsonify([{
        'id': t.id, 'room': t.room, 'issue': t.issue, 'author': t.author,
        'status': t.status, 'created_at': t.created_at.isoformat(),
        'priority': t.priority, 'category': t.category, 'comment': t.comment
    } for t in tickets])


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        room = request.form['room']
        issue = request.form['issue']
        author = request.form.get('author', 'Аноним')
        priority = request.form.get('priority', 'Обычная')
        category = request.form.get('category', '📝 Другое')
        ticket = Ticket(room=room, issue=issue, author=author, priority=priority, category=category)
        db.session.add(ticket)
        db.session.commit()

        send_push_notification(
            title=f"Новая заявка: каб. {room}",
            body=f"{category}: {issue[:40]}{'...' if len(issue) > 40 else ''}"
        )
        return redirect(url_for('index') + '?toast=created')
    return render_template('add.html')


@app.route('/progress/<int:ticket_id>')
@login_required
def progress(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.status = 'В работе'
    db.session.commit()
    return redirect(url_for('index') + '?toast=progress')


@app.route('/resolve/<int:ticket_id>')
@login_required
def resolve(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.status = 'Выполнено'
    db.session.commit()
    return redirect(url_for('index') + '?toast=resolved')


@app.route('/delete/<int:ticket_id>')
@login_required
def delete_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    db.session.delete(ticket)
    db.session.commit()
    return redirect(url_for('index') + '?toast=deleted')


@app.route('/comment/<int:ticket_id>', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.comment = request.form.get('comment', '').strip()
    db.session.commit()
    return redirect(url_for('index') + '?toast=commented')


@app.route('/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error"}), 400
    endpoint, keys = data.get('endpoint'), data.get('keys', {})
    p256dh, auth = keys.get('p256dh'), keys.get('auth')
    if not all([endpoint, p256dh, auth]):
        return jsonify({"status": "error"}), 400
    sub = Subscription.query.filter_by(endpoint=endpoint).first()
    if sub:
        sub.p256dh, sub.auth = p256dh, auth
    else:
        sub = Subscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
        db.session.add(sub)
    db.session.commit()
    return jsonify({"status": "ok"})


with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
