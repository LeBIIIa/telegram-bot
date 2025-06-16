from flask import Flask, request, render_template_string, redirect, abort
import os
import psycopg2
import uuid
import telegram
from datetime import datetime, timedelta

datetime_format = "%Y-%m-%d %H:%M:%S"
TOKEN_TTL_MINUTES = 10

app = Flask(__name__)
DB_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

def validate_token(token):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # Clean up expired tokens
    cur.execute("DELETE FROM admin_tokens WHERE now() - created_at > interval '%s minutes'", (TOKEN_TTL_MINUTES,))
    
    # Check if token exists and is valid
    cur.execute("SELECT telegram_id FROM admin_tokens WHERE token = %s", (token,))
    result = cur.fetchone()
    
    conn.commit()
    cur.close()
    conn.close()
    
    if not result:
        return None
    
    return result[0]  # Return the telegram_id associated with the token

def is_group_member(telegram_id):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        chat_member = bot.get_chat_member(chat_id=GROUP_ID, user_id=telegram_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except:
        return False

TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>Адмін-панель</title>
  <style>
    .status-New { color: gray; }
    .status-InProgress { color: blue; }
    .status-Accepted { color: green; }
    .status-Declined { color: red; }
    form.inline { display: inline; }
    .extra-fields { display: none; }
  </style>
</head>
<body>
<h2>📋 Надіслані заявки</h2>

<div>
  <b>🔎 Фільтр:</b>
  {% for s in ['New', 'In Progress', 'Accepted', 'Declined'] %}
    <a href="/admin?token={{ request.args.get('token') }}&status={{ s }}">
      <button>{{ s }}</button>
    </a>
  {% endfor %}
  <a href="/admin?token={{ request.args.get('token') }}">
    <button>🔁 Всі</button>
  </a>
</div>

<table border="1" cellpadding="5">
  <tr>
    <th>Ім'я</th><th>Вік</th><th>Місто</th><th>Телефон</th><th>Username</th>
    <th>Статус</th><th>Оновити</th>{% if is_admin %}<th>Видалити</th>{% endif %}
  </tr>
  {% for user in users %}
  <tr>
    <td>{{ user.name }}</td>
    <td>{{ user.age }}</td>
    <td>{{ user.city }}</td>
    <td>{{ user.phone or "—" }}</td>
    <td>
      {% if user.username %}
        <a href="https://t.me/{{ user.username }}" target="_blank">@{{ user.username }}</a>
      {% else %} — {% endif %}
    </td>
    <td class="status-{{ user.status.replace(' ', '') }}">{{ user.status }}</td>
    <td>
      <form method="post" action="/update" class="inline">
        <input type="hidden" name="telegram_id" value="{{ user.telegram_id }}">
        <select name="status" onchange="onStatusChange(this, '{{ user.telegram_id }}')">
          <option value="New" {% if user.status == "New" %}selected{% endif %}>New</option>
          <option value="In Progress" {% if user.status == "In Progress" %}selected{% endif %}>In Progress</option>
          <option value="Accepted" {% if user.status == "Accepted" %}selected{% endif %}>Accepted</option>
          <option value="Declined" {% if user.status == "Declined" %}selected{% endif %}>Declined</option>
        </select>
        <div id="extra-{{ user.telegram_id }}" class="extra-fields">
          <input type="text" name="accepted_city" placeholder="Місто" value="{{ user.accepted_city or '' }}">
          <input type="date" name="accepted_date" value="{{ user.accepted_date or '' }}">
        </div>
        <button type="submit">💾</button>
      </form>
    </td>
    {% if is_admin %}
    <td>
      <form method="post" action="/delete" class="inline">
        <input type="hidden" name="telegram_id" value="{{ user.telegram_id }}">
        <button type="submit">🗑️</button>
      </form>
    </td>
    {% endif %}
  </tr>
  {% endfor %}
</table>

<script>
function onStatusChange(select, id) {
  const showExtra = select.value === "Accepted";
  document.getElementById("extra-" + id).style.display = showExtra ? "block" : "none";
}
</script>
</body>
</html>
"""

@app.route("/admin")
def index():
    token = request.args.get("token")
    telegram_id = validate_token(token)
    if not telegram_id or not is_group_member(telegram_id):
        return abort(403)

    status_filter = request.args.get("status")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    query = """
        SELECT name, age, city, phone, username, telegram_id, status, 
               accepted_city, accepted_date::text
        FROM applicants
    """
    params = []

    if status_filter:
        query += " WHERE status = %s"
        params.append(status_filter)

    query += " ORDER BY id DESC"
    cur.execute(query, params)

    rows = cur.fetchall()
    users = [dict(
        name=r[0], age=r[1], city=r[2], phone=r[3], username=r[4],
        telegram_id=r[5], status=r[6], accepted_city=r[7], accepted_date=r[8]
    ) for r in rows]
    
    cur.close()
    conn.close()
    return render_template_string(TEMPLATE, users=users, is_admin=telegram_id == ADMIN_ID)

@app.route("/update", methods=["POST"])
def update_status():
    token = request.args.get("token")
    telegram_id = validate_token(token)
    if not telegram_id or not is_group_member(telegram_id):
        return abort(403)

    applicant_id = request.form["telegram_id"]
    new_status = request.form["status"]
    accepted_city = request.form.get("accepted_city")
    accepted_date = request.form.get("accepted_date")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    if new_status == "Accepted" and accepted_city and accepted_date:
        cur.execute("""
            UPDATE applicants
            SET status = %s, accepted_city = %s, accepted_date = %s
            WHERE telegram_id = %s
        """, (new_status, accepted_city, accepted_date, applicant_id))
    else:
        cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", (new_status, applicant_id))

    if new_status in ("Accepted", "Declined"):
        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))
        topic = cur.fetchone()
        if topic:
            bot = telegram.Bot(token=BOT_TOKEN)
            try:
                bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
            except:
                pass
            cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(f"/admin?token={token}")

@app.route("/delete", methods=["POST"])
def delete_user():
    token = request.args.get("token")
    telegram_id = validate_token(token)
    
    if not telegram_id or telegram_id != ADMIN_ID:
        return abort(403)

    applicant_id = request.form["telegram_id"]

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))
    topic = cur.fetchone()

    if topic:
        bot = telegram.Bot(token=BOT_TOKEN)
        try:
            bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
        except:
            pass
        cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))

    cur.execute("DELETE FROM applicants WHERE telegram_id = %s", (applicant_id,))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(f"/admin?token={token}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
