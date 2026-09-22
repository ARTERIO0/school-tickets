import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
DB_NAME = 'tickets.db'

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
def resolve(ticket_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tickets SET status = 'Выполнено' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)