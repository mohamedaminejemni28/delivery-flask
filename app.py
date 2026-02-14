from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3
import re
import os

app = Flask(__name__)

# Database path for Render
DB = os.path.join("/tmp", "delivery.db")


# ----------------------
# Helpers
# ----------------------

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def get_status(order_qty, delivered_qty):
    return "green" if delivered_qty >= order_qty else "red"


def extract_coordinates(text):
    match = re.search(r"([-+]?\d*\.\d+),\s*([-+]?\d*\.\d+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None


# ----------------------
# INIT DB
# ----------------------

def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            order_qty INTEGER DEFAULT 0,
            delivered_qty INTEGER DEFAULT 0,
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

    if "key" in data:

        raw_text = data.get("key", "")

        phone_match = re.search(r"De\s*:\s*\+?(\d+)", raw_text)
        phone = phone_match.group(1) if phone_match else "unknown"

        name_match = re.search(r"\((.*?)\)", raw_text)
        name = name_match.group(1) if name_match else "client"

        body_match = re.search(r"\n(.+)", raw_text, re.DOTALL)
        body = body_match.group(1) if body_match else raw_text

    elif "From" in data:

        phone = normalize_phone(data.get("From"))
        body = data.get("Body", "")
        name = body.split()[0] if body else "client"

    if not status_term:
        status_term = body

    latitude, longitude = extract_coordinates(body)

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("SELECT order_qty, delivered_qty FROM clients WHERE phone=?", (phone,))
        row = c.fetchone()

        if row:

            order_qty = row[0] + 1
            delivered_qty = row[1]

            status = get_status(order_qty, delivered_qty)

            c.execute("""

            UPDATE clients
            SET
                order_qty=?,
                name=?,
                latitude=?,
                longitude=?,
                status=?,
                status_term=?,
                last_request_time=?

            WHERE phone=?

            """, (
                order_qty,
                name,
                latitude,
                longitude,
                status,
                status_term,
                datetime.utcnow(),
                phone
            ))

        else:

            c.execute("""

            INSERT INTO clients
            (
                name,
                phone,
                order_qty,
                delivered_qty,
                status,
                status_term,
                latitude,
                longitude,
                last_request_time
            )

            VALUES (?,?,?,?,?,?,?,?,?)

            """, (
                name,
                phone,
                1,
                0,
                "red",
                status_term,
                latitude,
                longitude,
                datetime.utcnow()
            ))

        c.execute("""

        INSERT INTO messages
        (phone, body, received_at)

        VALUES (?,?,?)

        """, (phone, status_term, datetime.utcnow()))

        conn.commit()

    return "OK", 200


# ----------------------
# GET CLIENTS (FIXED)
# ----------------------

@app.route("/clients", methods=["GET"])
def clients():

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""

        SELECT
        client_id,
        name,
        phone,
        order_qty,
        delivered_qty,
        status,
        status_term,
        latitude,
        longitude,
        last_request_time

        FROM clients

        """)

        rows = c.fetchall()

    return jsonify([

        {
            "client_id": r[0],
            "name": r[1],
            "phone": r[2],
            "order_qty": r[3],
            "delivered_qty": r[4],
            "status": r[5],
            "status_term": r[6],
            "latitude": r[7],
            "longitude": r[8],
            "last_request_time": r[9]
        }

        for r in rows

    ])


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

    return jsonify([

        {
            "message_id": r[0],
            "phone": r[1],
            "body": r[2],
            "received_at": r[3]
        }

        for r in rows

    ])


# ----------------------
# DELIVER
# ----------------------

@app.route("/deliver", methods=["POST"])
def deliver():

    data = request.get_json()

    name = data.get("name")

    qty = int(data.get("delivered_qty", 1))

    with sqlite3.connect(DB) as conn:

        c = conn.cursor()

        c.execute("""

        SELECT order_qty, delivered_qty
        FROM clients
        WHERE name=?

        """, (name,))

        row = c.fetchone()

        if row:

            delivered = row[1] + qty

            status = get_status(row[0], delivered)

            c.execute("""

            UPDATE clients
            SET delivered_qty=?, status=?

            WHERE name=?

            """, (delivered, status, name))

            conn.commit()

            return jsonify({"status": status})

    return jsonify({"error": "not found"}), 404


# ----------------------
# ROOT
# ----------------------

@app.route("/")
def home():
    return "Delivery API Running"
