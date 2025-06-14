
import os
import psycopg2
from flask import Flask, request, redirect, url_for, render_template_string
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")

TEMPLATE = """
<!doctype html>
<title>Admin Panel</title>
<h2>Надіслані заявки</h2>
{% raw %}
{% if users %}
<table border="1" cellpadding="5">
    <tr><th>Ім’я</th><th>Вік</th><th>Місто</th><th>Дія</th></tr>
    {% for user in users %}
    <tr>
        <td>{{ user.name }}</td>
        <td>{{ user.age }}</td>
        <td>{{ user.city }}</td>
        <td>
            <form action="/reply" method="post" style="display:inline;">
                <input type="hidden" name="chat_id" value="{{ user.telegram_id }}">
                <input type="text" name="message" placeholder="Ваша відповідь" required>
                <button type="submit">Відправити</button>
            </form>
        </td>
    </tr>
    {% endfor %}
</table>
{% else %}
<p>Заявок ще немає.</p>
{% endif %}
{% endraw %}
"""

def ensure_table():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
CREATE TABLE IF NOT EXISTS applicants (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER NOT NULL,
    city TEXT NOT NULL,
    telegram_id BIGINT NOT NULL
);
""")
    conn.commit()
    cur.close()
    conn.close()

@app.route("/")
def index():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT name, age, city, telegram_id FROM applicants ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    users = [{"name": r[0], "age": r[1], "city": r[2], "telegram_id": r[3]} for r in rows]
    return render_template_string(TEMPLATE, users=users)

@app.route("/reply", methods=["POST"])
def reply():
    chat_id = request.form["chat_id"]
    message = request.form["message"]

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, data=payload)

    return redirect(url_for("index"))

if __name__ == "__main__":
    ensure_table()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
