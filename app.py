
from flask import Flask, request, render_template_string, redirect
import os
import psycopg2

app = Flask(__name__)
DB_URL = os.getenv("DATABASE_URL")

TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>Admin Panel</title>
  <style>
    .status-New { color: gray; }
    .status-InProgress { color: blue; }
    .status-Accepted { color: green; }
    .status-Declined { color: red; }
  </style>
</head>
<body>
<h2>Надіслані заявки</h2>
<table border="1" cellpadding="5">
  <tr><th>Ім’я</th><th>Вік</th><th>Місто</th><th>Телефон</th><th>Username</th><th>Статус</th><th>Оновити</th></tr>
  {% for user in users %}
  <tr>
    <td>{{ user.name }}</td>
    <td>{{ user.age }}</td>
    <td>{{ user.city }}</td>
    <td>{{ user.phone or "—" }}</td>
    <td>
      {% if user.username %}
        <a href="https://t.me/{{ user.username }}" target="_blank">@{{ user.username }}</a>
      {% else %}
        —
      {% endif %}
    </td>
    <td class="status-{{ user.status.replace(' ', '') }}">{{ user.status }}</td>
    <td>
      <form method="post" action="/update">
        <input type="hidden" name="telegram_id" value="{{ user.telegram_id }}">
        <select name="status">
          <option value="New" {% if user.status == "New" %}selected{% endif %}>New</option>
          <option value="In Progress" {% if user.status == "In Progress" %}selected{% endif %}>In Progress</option>
          <option value="Accepted" {% if user.status == "Accepted" %}selected{% endif %}>Accepted</option>
          <option value="Declined" {% if user.status == "Declined" %}selected{% endif %}>Declined</option>
        </select>
        <button type="submit">💾</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT name, age, city, phone, username, telegram_id, status FROM applicants ORDER BY id DESC")
    rows = cur.fetchall()
    users = [
        dict(name=r[0], age=r[1], city=r[2], phone=r[3], username=r[4], telegram_id=r[5], status=r[6])
        for r in rows
    ]
    cur.close()
    conn.close()
    return render_template_string(TEMPLATE, users=users)

@app.route("/update", methods=["POST"])
def update_status():
    telegram_id = request.form["telegram_id"]
    new_status = request.form["status"]

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", (new_status, telegram_id))
    conn.commit()
    cur.close()
    conn.close()

    return redirect("/")
