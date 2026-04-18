import base64
import logging
import os
import sqlite3
import threading

import requests
from flask import Flask, jsonify, redirect, request, Response, url_for
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

load_dotenv()

FAL_KEY = os.getenv("FAL_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
DATABASE_PATH = os.getenv("DATABASE_PATH", "jewelbot.db")
db_lock = threading.Lock()

EDITORIAL_PROMPT = """First, carefully identify what kind of jewelry or accessory is shown in the input image. Determine whether it is a ring, necklace, pendant, bracelet, bangle, earrings, anklet, nose pin, brooch, waist chain, or another wearable fashion accessory.

Then create a premium professional fashion shoot featuring a realistic model wearing that exact item naturally.

Preserve the jewelry with full fidelity:
- keep the exact design
- keep the exact shape and structure
- keep the exact metal finish and color
- keep the exact gemstones, detailing, texture, reflections, and craftsmanship
- do not redesign, simplify, exaggerate, or replace the item

Choose the model styling and pose based on the jewelry type:
- necklaces, pendants, earrings, nose pins: elegant beauty/fashion portrait
- rings, bracelets, bangles: premium hand/upper-body fashion composition
- brooches or waist chains: editorial full or half body styling where appropriate

The output should feel like a luxury brand campaign image:
- high-end fashion editorial
- professional studio or premium lifestyle setting
- realistic model styling, makeup, hair, wardrobe, and pose
- cinematic yet commercially usable composition

Placement must be physically believable:
- the item must be worn on the correct body part
- scale must be realistic
- fit and orientation must be natural
- no floating, clipping, or fake pasted look

Lighting and realism:
- match realistic studio or luxury campaign lighting
- preserve metallic reflections and gemstone shine naturally
- add accurate shadows and skin/clothing interaction
- keep anatomy, pose, and perspective realistic

Output style:
- ultra-realistic
- luxury jewelry ad
- Vogue / high-fashion campaign quality
- polished color grading
- sharp focus on the jewelry while keeping the overall image premium and believable

Strict rules:
- do not change the jewelry design
- do not generate a product flat lay
- do not create a mannequin-only image
- final result must be a professional model shoot featuring that exact jewelry item naturally"""


def get_twilio_client():
    if not TWILIO_SID or not TWILIO_TOKEN:
        raise RuntimeError("Missing TWILIO_SID or TWILIO_TOKEN environment variables.")
    return Client(TWILIO_SID, TWILIO_TOKEN)


def get_db_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_lock:
        connection = get_db_connection()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    phone_number TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    remaining_credits INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()
        finally:
            connection.close()


def client_to_dict(row):
    if row is None:
        return None
    return {
        "phone_number": row["phone_number"],
        "name": row["name"],
        "status": row["status"],
        "remaining_credits": row["remaining_credits"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_clients():
    connection = get_db_connection()
    try:
        rows = connection.execute(
            """
            SELECT phone_number, name, status, remaining_credits, created_at, updated_at
            FROM clients
            ORDER BY created_at DESC, phone_number ASC
            """
        ).fetchall()
        return [client_to_dict(row) for row in rows]
    finally:
        connection.close()


def get_client(phone_number):
    connection = get_db_connection()
    try:
        row = connection.execute(
            """
            SELECT phone_number, name, status, remaining_credits, created_at, updated_at
            FROM clients
            WHERE phone_number = ?
            """,
            (phone_number,),
        ).fetchone()
        return client_to_dict(row)
    finally:
        connection.close()


def upsert_client(phone_number, name, remaining_credits, status):
    with db_lock:
        connection = get_db_connection()
        try:
            connection.execute(
                """
                INSERT INTO clients (phone_number, name, status, remaining_credits)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(phone_number) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    remaining_credits = excluded.remaining_credits,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (phone_number, name, status, remaining_credits),
            )
            connection.commit()
        finally:
            connection.close()
    return get_client(phone_number)


def consume_credit(phone_number):
    with db_lock:
        connection = get_db_connection()
        try:
            row = connection.execute(
                """
                SELECT phone_number, name, status, remaining_credits, created_at, updated_at
                FROM clients
                WHERE phone_number = ?
                """,
                (phone_number,),
            ).fetchone()
            if row is None:
                return None, "not_onboarded"
            if row["status"] != "active":
                return client_to_dict(row), "inactive"
            if row["remaining_credits"] <= 0:
                return client_to_dict(row), "no_credits"

            connection.execute(
                """
                UPDATE clients
                SET remaining_credits = remaining_credits - 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE phone_number = ?
                """,
                (phone_number,),
            )
            connection.commit()
        finally:
            connection.close()
    return get_client(phone_number), None


def refund_credit(phone_number):
    with db_lock:
        connection = get_db_connection()
        try:
            connection.execute(
                """
                UPDATE clients
                SET remaining_credits = remaining_credits + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE phone_number = ?
                """,
                (phone_number,),
            )
            connection.commit()
        finally:
            connection.close()
    return get_client(phone_number)


def get_admin_key():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1).strip()
    return request.headers.get("X-Admin-Key") or request.args.get("admin_key")


def require_admin():
    if not ADMIN_API_KEY:
        return False, Response("ADMIN_API_KEY is not configured.", status=503)
    if get_admin_key() != ADMIN_API_KEY:
        return False, Response("Unauthorized", status=401)
    return True, None


def render_admin_page():
    admin_key = get_admin_key() or ""
    rows = []
    for client in list_clients():
        rows.append(
            f"""
            <tr>
                <td>{client['name']}</td>
                <td>{client['phone_number']}</td>
                <td>{client['status']}</td>
                <td>{client['remaining_credits']}</td>
                <td>{client['updated_at']}</td>
            </tr>
            """
        )

    table_rows = "".join(rows) or "<tr><td colspan='5'>No clients onboarded yet.</td></tr>"
    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Jewelbot Admin</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 32px; background: #faf8f4; color: #1c1814; }}
        h1, h2 {{ margin-bottom: 12px; }}
        form, table {{ background: white; border: 1px solid #ddd3c5; border-radius: 12px; padding: 20px; }}
        form {{ max-width: 520px; margin-bottom: 24px; }}
        label {{ display: block; margin-top: 12px; font-weight: 600; }}
        input, select, button {{ width: 100%; padding: 10px; margin-top: 6px; box-sizing: border-box; }}
        button {{ background: #111; color: white; border: 0; border-radius: 8px; cursor: pointer; margin-top: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #eee; }}
      </style>
    </head>
    <body>
      <h1>Jewelbot Admin</h1>
      <p>Onboard clients, activate or deactivate access, and manage remaining credits.</p>

      <form method="post" action="/admin/clients?admin_key={admin_key}">
        <h2>Add Or Update Client</h2>
        <label>Client Name
          <input type="text" name="name" placeholder="Client name" required>
        </label>
        <label>WhatsApp Number
          <input type="text" name="phone_number" placeholder="whatsapp:+9198xxxxxxx" required>
        </label>
        <label>Remaining Credits
          <input type="number" name="remaining_credits" min="0" value="10" required>
        </label>
        <label>Status
          <select name="status">
            <option value="active">active</option>
            <option value="inactive">inactive</option>
          </select>
        </label>
        <button type="submit">Save Client</button>
      </form>

      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Phone</th>
            <th>Status</th>
            <th>Credits</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </body>
    </html>
    """


def send_whatsapp(to, image_url, body="✨ Done!"):
    get_twilio_client().messages.create(
        from_='whatsapp:+14155238886',
        to=to,
        body=body,
        media_url=[image_url]
    )


def send_whatsapp_text(to, body):
    get_twilio_client().messages.create(
        from_='whatsapp:+14155238886',
        to=to,
        body=body,
    )


def process_editorial_shoot(user, reference_image):
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": EDITORIAL_PROMPT,
        "image_urls": [
            f"data:image/jpeg;base64,{reference_image}",
        ],
    }

    try:
        response = requests.post(
            "https://fal.run/fal-ai/nano-banana-2/edit",
            headers=headers,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()
        app.logger.info("Fal editorial response for %s: %s", user, result)

        images = result.get("images") or []
        if not images or not images[0].get("url"):
            refunded_client = refund_credit(user)
            send_whatsapp_text(
                user,
                f"Professional shoot create avvaledu. Credit malli add chesam. Remaining credits: {refunded_client['remaining_credits']}.",
            )
            return

        client = get_client(user)
        remaining = client["remaining_credits"] if client else 0
        send_whatsapp(user, images[0]["url"], body=f"✨ Done! Remaining credits: {remaining}")
    except Exception:
        app.logger.exception("Editorial shoot generation failed for %s", user)
        refunded_client = refund_credit(user)
        send_whatsapp_text(
            user,
            f"Professional shoot generate cheyyaledu. Credit malli add chesam. Remaining credits: {refunded_client['remaining_credits']}.",
        )


@app.route("/", methods=["GET"])
def home():
    return jsonify(
        {
            "status": "ok",
            "service": "jewelbot",
            "webhook": "/bot",
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/admin", methods=["GET"])
def admin_dashboard():
    authorized, error = require_admin()
    if not authorized:
        return error
    return render_admin_page()


@app.route("/admin/clients", methods=["GET", "POST"])
def admin_clients():
    authorized, error = require_admin()
    if not authorized:
        return error

    if request.method == "GET":
        return jsonify({"clients": list_clients()})

    payload = request.get_json(silent=True) or request.form
    phone_number = (payload.get("phone_number") or "").strip()
    name = (payload.get("name") or "").strip()
    status = (payload.get("status") or "active").strip().lower()

    if not phone_number.startswith("whatsapp:"):
        return Response("phone_number must be in whatsapp:+<countrycode><number> format.", status=400)
    if not name:
        return Response("name is required.", status=400)
    if status not in {"active", "inactive"}:
        return Response("status must be active or inactive.", status=400)

    try:
        remaining_credits = int(payload.get("remaining_credits", 0))
    except (TypeError, ValueError):
        return Response("remaining_credits must be an integer.", status=400)

    if remaining_credits < 0:
        return Response("remaining_credits cannot be negative.", status=400)

    client = upsert_client(phone_number, name, remaining_credits, status)

    if request.form:
        return redirect(url_for("admin_dashboard", admin_key=get_admin_key()))

    return jsonify({"client": client})


@app.route("/bot", methods=["POST"])
def bot():
    resp = MessagingResponse()
    msg = resp.message()

    if not FAL_KEY or not TWILIO_SID or not TWILIO_TOKEN:
        msg.body("Server configuration is incomplete. Please contact support.")
        return str(resp)

    media_url = request.values.get("MediaUrl0")
    user = request.values.get("From")
    client = get_client(user) if user else None

    if not client:
        msg.body("Mee WhatsApp number onboard avvaledu. Support ni contact cheyandi.")
        return str(resp)

    if client["status"] != "active":
        msg.body("Mee access ippudu inactive ga undi. Support ni contact cheyandi.")
        return str(resp)

    if media_url:
        updated_client, error = consume_credit(user)
        if error == "no_credits":
            msg.body("Mee credits aipoyayi. Support ni contact cheyandi.")
            return str(resp)
        if error in {"not_onboarded", "inactive"}:
            msg.body("Mee account use cheyyadaniki ready ga ledu. Support ni contact cheyandi.")
            return str(resp)

        # download image
        try:
            img = requests.get(media_url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=30)
            img.raise_for_status()
        except Exception:
            refunded_client = refund_credit(user)
            msg.body(
                "Image download avvaledu. Credit malli add chesam. "
                f"Remaining credits: {refunded_client['remaining_credits']}."
            )
            return str(resp)

        image_bytes = img.content
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        msg.body(
            "⏳ Creating professional jewelry shoot...\n"
            f"Remaining credits after this request: {updated_client['remaining_credits']}"
        )
        thread = threading.Thread(
            target=process_editorial_shoot,
            args=(user, image_base64),
            daemon=True,
        )
        thread.start()

    else:
        msg.body(
            "Jewellery image send cheyandi 💎\n"
            f"Remaining credits: {client['remaining_credits']}"
        )

    return str(resp)


init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
