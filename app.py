from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3
import re
import os

app = Flask(__name__)

# ✅ DB persistante
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "delivery.db")


# ----------------------
# Helpers
# ----------------------

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def get_status(order_qty, delivered_qty):
    return "green" if delivered_qty >= order_qty else "red"


# ----------------------
# DB init
# ----------------------

def init_db():
    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            order_qty INTEGER,
            delivered_qty INTEGER,
            status TEXT,
            status_term TEXT,
            latitude REAL,
            longitude REAL,
            last_request_time TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            body TEXT,
            received_at TEXT
        )
        """)

        conn.commit()


init_db()


# ----------------------
# RECEIVE SMS
# ----------------------

@app.route("/sms", methods=["POST"])
def receive_sms():

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    print("RAW DATA:", data)

    phone = ""
    name = ""
    body = ""
    status_term = data.get("status", "").strip()


    # custom sms forwarder
    if "key" in data:

        raw_text = data.get("key", "").strip()

        phone_match = re.search(r"De\s*:\s*\+?(\d+)", raw_text)
        phone = phone_match.group(1) if phone_match else "UNKNOWN"

        name_match = re.search(r"\((.*?)\)", raw_text)
        name = name_match.group(1) if name_match else "Unknown"

        body_match = re.search(r"\n(.+)", raw_text, re.DOTALL)
        body = body_match.group(1) if body_match else raw_text


    elif "From" in data:

        phone = normalize_phone(data.get("From"))
        body = data.get("Body", "")
        name = body.split()[0] if body else "Unknown"


    if not status_term:
        status_term = body


    status = "red"


    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("SELECT order_qty, delivered_qty FROM clients WHERE phone=?",(phone,))
        row = c.fetchone()

        if row:

            order_qty = row[0] + 1
            delivered_qty = row[1]

            c.execute("""
            UPDATE clients
            SET order_qty=?,
            last_request_time=?,
            name=?,
            status_term=?,
            status=?
            WHERE phone=?
            """,

            (order_qty,
            datetime.utcnow(),
            name,
            status_term,
            status,
            phone))

        else:

            c.execute("""
            INSERT INTO clients
            (name, phone, order_qty, delivered_qty, status, status_term, last_request_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,

            (
                name,
                phone,
                1,
                0,
                status,
                status_term,
                datetime.utcnow()
            ))


        c.execute("""
        INSERT INTO messages
        (phone, body, received_at)
        VALUES (?, ?, ?)
        """,

        (
            phone,
            status_term,
            datetime.utcnow()
        ))


        conn.commit()


    return "OK", 200


# ----------------------
# GET MESSAGES
# ----------------------

@app.route("/messages", methods=["GET"])
def messages():

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""
        SELECT message_id, phone, body, received_at
        FROM messages
        ORDER BY received_at DESC
        """)

        rows = c.fetchall()

    return jsonify(rows)


# ----------------------
# GET CLIENTS
# ----------------------

@app.route("/clients", methods=["GET"])
def clients():

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""
        SELECT *
        FROM clients
        """)

        rows = c.fetchall()

    return jsonify(rows)


# ----------------------
# DELIVER
# ----------------------

@app.route("/deliver", methods=["POST"])
def deliver():

    data = request.get_json()

    name = data.get("name")

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""
        UPDATE clients
        SET delivered_qty = delivered_qty + 1
        WHERE name=?
        """,(name,))

        conn.commit()

    return "OK"
