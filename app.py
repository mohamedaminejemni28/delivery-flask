from flask import Flask, request, jsonify
from datetime import datetime
import sqlite3
import re

app = Flask(__name__)
DB = "delivery.db"



# ----------------------
# Helpers
# ----------------------
def dms_to_decimal(dms_str):
    """Convertit une coordonnée DMS (ex: 34°47'39.2N) en décimal"""
    match = re.match(r"(\d+)°\s*(\d+)'\s*([\d\.]+)\s*([NSEW])", dms_str.strip(), re.IGNORECASE)
    if not match:
        return None
    deg, minutes, seconds, direction = match.groups()
    dec = float(deg) + float(minutes)/60 + float(seconds)/3600
    if direction.upper() in ['S','W']:
        dec = -dec
    return dec






def extract_coordinates(text):
    """Extrait les coordonnées depuis un texte en format décimal ou DMS"""
    # Format décimal "lat, lon"
    match = re.search(r"([-+]?\d*\.\d+),\s*([-+]?\d*\.\d+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    
    # Format DMS
    dms_match = re.findall(r"(\d+°\s*\d+'\s*[\d\.]+\s*[NSEW])", text, re.IGNORECASE)
    if len(dms_match) == 2:
        return dms_to_decimal(dms_match[0]), dms_to_decimal(dms_match[1])
    
    return None, None





def normalize_phone(phone: str) -> str:
    """Nettoie un numéro de téléphone pour ne garder que les chiffres"""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)

def get_status(order_qty, delivered_qty):
    """Retourne le status coloré selon la livraison"""
    return "green" if delivered_qty >= order_qty else "red"

# ----------------------
# DB setup
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









@app.route("/delete_client", methods=["POST"])
def delete_client():
    data = request.get_json() or {}
    name = data.get("name")
    client_id = data.get("client_id")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    if name:
        c.execute("DELETE FROM clients WHERE name=?", (name,))
    elif client_id:
        c.execute("DELETE FROM clients WHERE client_id=?", (client_id,))
    else:
        conn.close()
        return jsonify({"deleted": False, "error": "No identifier provided"}), 400
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return jsonify({"deleted": deleted})







# ----------------------
# RECEIVE SMS (Webhook)
# ----------------------
@app.route("/sms", methods=["POST"])
def receive_sms():
    data = request.form.to_dict()
    print("RAW DATA:", data)

    phone = ""
    name = ""
    body = ""
    status_term = data.get("status", "").strip()

    # --- CASE 1: custom "key" format ---
    if "key" in data:
        raw_text = data.get("key", "").strip()

        # Tenter d'extraire le phone
        phone_match = re.search(r"De\s*:\s*\+?(\d+)", raw_text)
        phone = phone_match.group(1) if phone_match else "TEST_PHONE"

        # Tenter d'extraire le nom
        name_match = re.search(r"\((.*?)\)", raw_text)
        name = name_match.group(1).strip() if name_match else "TEST_NAME"

        # Tenter d'extraire le corps du message
        body_match = re.search(r"\n(.+)", raw_text, re.DOTALL)
        body = body_match.group(1).strip() if body_match else raw_text

    # --- CASE 2: Twilio/From+Body ---
    elif "From" in data and "Body" in data:
        phone = normalize_phone(data.get("From"))
        body = data.get("Body", "").strip()
        name = body.split()[0].capitalize() if body else "Unknown"

    # Si aucun status fourni, utiliser le body
    if not status_term:
        status_term = body

    latitude, longitude = extract_coordinates(body)

    # --- Forcer status à "red" ---
    status = "red"

    # --- DB update ---
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("SELECT order_qty, delivered_qty, latitude, longitude FROM clients WHERE phone=?", (phone,))
        row = c.fetchone()

        if row:
            order_qty = row[0] + 1
            delivered_qty = row[1]
            latitude = latitude or row[2]
            longitude = longitude or row[3]

            c.execute("""
                UPDATE clients
                SET order_qty=?, last_request_time=?, name=?, latitude=?, longitude=?, status_term=?, status=?
                WHERE phone=?
            """, (order_qty, datetime.utcnow(), name, latitude, longitude, status_term, status, phone))
        else:
            order_qty = 1
            delivered_qty = 0
            c.execute("""
                INSERT INTO clients (
                    name, phone, order_qty, delivered_qty, status, status_term, latitude, longitude, last_request_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, phone, order_qty, delivered_qty, status, status_term, latitude or 36.8065, longitude or 10.1815, datetime.utcnow()))

        # --- Historique des messages ---
        c.execute("INSERT INTO messages (phone, body, received_at) VALUES (?, ?, ?)", (phone, status_term, datetime.utcnow()))

    return "OK", 200














# GET MESSAGES
# ----------------------
@app.route("/messages", methods=["GET"])
def get_messages():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT m.message_id, m.phone, c.name, m.body, m.received_at
            FROM messages m
            LEFT JOIN clients c ON m.phone = c.phone
            ORDER BY m.received_at DESC
        """)
        rows = c.fetchall()

    return jsonify([
        {"message_id": r[0], "phone": r[1], "name": r[2], "body": r[3], "received_at": r[4]}
        for r in rows
    ])

# ----------------------
# GET CLIENTS
# ----------------------
@app.route("/clients", methods=["GET"])
def clients():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("SELECT client_id, name, phone, order_qty, delivered_qty, status, status_term, latitude, longitude FROM clients")
        rows = c.fetchall()

    return jsonify([
        {"client_id": r[0], "name": r[1], "phone": r[2], "order_qty": r[3], "delivered_qty": r[4],
         "status": r[5], "status_term": r[6], "latitude": r[7], "longitude": r[8]}
        for r in rows
    ])

# ----------------------
# DELIVER
# ----------------------
@app.route("/deliver", methods=["POST"])
def deliver():
    data = request.get_json() or {}
    name = data.get("name")
    qty = int(data.get("delivered_qty", 1))

    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("SELECT order_qty, delivered_qty FROM clients WHERE name=?", (name,))
        row = c.fetchone()
        if row:
            delivered = row[1] + qty
            status = get_status(row[0], delivered)
            c.execute("UPDATE clients SET delivered_qty=?, status=? WHERE name=?", (delivered, status, name))
            conn.commit()
            return jsonify({"status": status})

    return jsonify({"error": "Client not found"}), 404

# ----------------------
# RUN
# ----------------------
#if __name__ == "__main__":
    #app.run(debug=True)
