import base64
import html
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
    clients = list_clients()
    total_clients = len(clients)
    active_clients = sum(1 for client in clients if client["status"] == "active")
    inactive_clients = total_clients - active_clients
    total_credits = sum(client["remaining_credits"] for client in clients)
    rows = []
    for client in clients:
        status_class = "status-active" if client["status"] == "active" else "status-inactive"
        rows.append(
            f"""
            <tr>
                <td>
                  <div class="client-name">{html.escape(client['name'])}</div>
                  <div class="client-meta">Updated {html.escape(client['updated_at'])}</div>
                </td>
                <td><span class="phone-pill">{html.escape(client['phone_number'])}</span></td>
                <td><span class="status-pill {status_class}">{html.escape(client['status'].title())}</span></td>
                <td><strong>{client['remaining_credits']}</strong></td>
                <td>{html.escape(client['updated_at'])}</td>
            </tr>
            """
        )

    table_rows = "".join(rows) or """
    <tr>
      <td colspan="5">
        <div class="empty-state">
          <div class="empty-title">No clients onboarded yet</div>
          <div class="empty-copy">Add your first WhatsApp number above to start controlling access and credits.</div>
        </div>
      </td>
    </tr>
    """
    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Jewelbot Admin</title>
      <style>
        :root {{
          --ink: #171214;
          --muted: #6f6569;
          --line: rgba(74, 53, 60, 0.14);
          --card: rgba(255, 252, 249, 0.9);
          --card-strong: rgba(255, 255, 255, 0.96);
          --glow: #f2d7c6;
          --accent: #a6493a;
          --accent-dark: #7d2f23;
          --active-bg: #edf8ef;
          --active-ink: #1f6a3f;
          --inactive-bg: #fdf1ef;
          --inactive-ink: #9d4234;
          --shadow: 0 24px 60px rgba(70, 44, 33, 0.16);
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          color: var(--ink);
          font-family: "Trebuchet MS", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at top left, rgba(255, 223, 196, 0.95), transparent 28%),
            radial-gradient(circle at top right, rgba(225, 194, 210, 0.72), transparent 24%),
            linear-gradient(180deg, #f9efe7 0%, #f7f1eb 42%, #f4ede7 100%);
        }}
        .shell {{
          max-width: 1240px;
          margin: 0 auto;
          padding: 32px 20px 48px;
        }}
        .hero {{
          position: relative;
          overflow: hidden;
          padding: 34px;
          border: 1px solid rgba(255, 255, 255, 0.55);
          border-radius: 28px;
          background:
            linear-gradient(135deg, rgba(255,255,255,0.78), rgba(255,248,242,0.66)),
            linear-gradient(145deg, rgba(255,255,255,0.15), rgba(166,73,58,0.08));
          box-shadow: var(--shadow);
          backdrop-filter: blur(16px);
        }}
        .hero::after {{
          content: "";
          position: absolute;
          inset: auto -60px -80px auto;
          width: 240px;
          height: 240px;
          border-radius: 50%;
          background: radial-gradient(circle, rgba(166,73,58,0.16), transparent 70%);
        }}
        .eyebrow {{
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.72);
          color: var(--accent-dark);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }}
        h1 {{
          margin: 18px 0 10px;
          font-size: clamp(2.1rem, 5vw, 4rem);
          line-height: 0.95;
          letter-spacing: -0.04em;
        }}
        .hero-copy {{
          max-width: 720px;
          margin: 0;
          font-size: 1rem;
          line-height: 1.7;
          color: var(--muted);
        }}
        .stats {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 14px;
          margin-top: 26px;
        }}
        .stat-card {{
          padding: 18px;
          border: 1px solid rgba(255,255,255,0.7);
          border-radius: 22px;
          background: rgba(255,255,255,0.78);
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.55);
        }}
        .stat-label {{
          margin: 0 0 10px;
          color: var(--muted);
          font-size: 0.82rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }}
        .stat-value {{
          margin: 0;
          font-size: 2rem;
          font-weight: 800;
          letter-spacing: -0.04em;
        }}
        .layout {{
          display: grid;
          grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
          gap: 22px;
          margin-top: 24px;
          align-items: start;
        }}
        .panel {{
          border: 1px solid var(--line);
          border-radius: 26px;
          background: var(--card);
          box-shadow: var(--shadow);
          backdrop-filter: blur(16px);
        }}
        .panel-inner {{
          padding: 24px;
        }}
        .panel h2 {{
          margin: 0;
          font-size: 1.3rem;
          letter-spacing: -0.03em;
        }}
        .panel-copy {{
          margin: 8px 0 0;
          color: var(--muted);
          line-height: 1.65;
          font-size: 0.96rem;
        }}
        form {{
          display: grid;
          gap: 14px;
          margin-top: 22px;
        }}
        .field {{
          display: grid;
          gap: 8px;
        }}
        label {{
          font-size: 0.9rem;
          font-weight: 700;
          color: #34282d;
        }}
        input, select, button {{
          width: 100%;
          border-radius: 16px;
          border: 1px solid rgba(96, 72, 80, 0.16);
          padding: 13px 14px;
          font: inherit;
        }}
        input, select {{
          color: var(--ink);
          background: var(--card-strong);
          outline: none;
          transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
        }}
        input:focus, select:focus {{
          border-color: rgba(166, 73, 58, 0.5);
          box-shadow: 0 0 0 4px rgba(166, 73, 58, 0.12);
          transform: translateY(-1px);
        }}
        .field-hint {{
          margin: -2px 0 0;
          color: var(--muted);
          font-size: 0.82rem;
        }}
        button {{
          border: 0;
          color: white;
          font-weight: 800;
          letter-spacing: 0.01em;
          cursor: pointer;
          background: linear-gradient(135deg, var(--accent), var(--accent-dark));
          box-shadow: 0 16px 32px rgba(125, 47, 35, 0.28);
          transition: transform 0.18s ease, box-shadow 0.18s ease, opacity 0.18s ease;
        }}
        button:hover {{
          transform: translateY(-1px);
          box-shadow: 0 20px 38px rgba(125, 47, 35, 0.34);
        }}
        .table-wrap {{
          overflow: hidden;
        }}
        .table-header {{
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: flex-start;
          margin-bottom: 18px;
        }}
        .table-note {{
          margin: 6px 0 0;
          color: var(--muted);
          font-size: 0.9rem;
        }}
        .table-shell {{
          overflow-x: auto;
          border: 1px solid rgba(96, 72, 80, 0.12);
          border-radius: 20px;
          background: rgba(255,255,255,0.72);
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          min-width: 720px;
        }}
        th, td {{
          text-align: left;
          padding: 16px 18px;
          border-bottom: 1px solid rgba(96, 72, 80, 0.1);
          vertical-align: middle;
        }}
        th {{
          color: var(--muted);
          font-size: 0.78rem;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          background: rgba(249, 242, 237, 0.92);
        }}
        tr:last-child td {{
          border-bottom: 0;
        }}
        .client-name {{
          font-weight: 800;
          letter-spacing: -0.01em;
        }}
        .client-meta {{
          margin-top: 4px;
          color: var(--muted);
          font-size: 0.82rem;
        }}
        .phone-pill, .status-pill {{
          display: inline-flex;
          align-items: center;
          border-radius: 999px;
          padding: 8px 12px;
          font-size: 0.84rem;
          font-weight: 700;
        }}
        .phone-pill {{
          background: rgba(245, 238, 232, 0.94);
          color: #4d3e41;
        }}
        .status-active {{
          background: var(--active-bg);
          color: var(--active-ink);
        }}
        .status-inactive {{
          background: var(--inactive-bg);
          color: var(--inactive-ink);
        }}
        .empty-state {{
          padding: 36px 16px;
          text-align: center;
        }}
        .empty-title {{
          font-size: 1.1rem;
          font-weight: 800;
          letter-spacing: -0.02em;
        }}
        .empty-copy {{
          margin-top: 8px;
          color: var(--muted);
          line-height: 1.6;
        }}
        @media (max-width: 980px) {{
          .stats {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }}
          .layout {{
            grid-template-columns: 1fr;
          }}
        }}
        @media (max-width: 640px) {{
          .shell {{
            padding: 18px 14px 34px;
          }}
          .hero {{
            padding: 24px 18px;
            border-radius: 24px;
          }}
          .stats {{
            grid-template-columns: 1fr;
          }}
          .panel-inner {{
            padding: 18px;
          }}
          .table-header {{
            flex-direction: column;
          }}
        }}
      </style>
    </head>
    <body>
      <div class="shell">
        <section class="hero">
          <div class="eyebrow">Jewelbot Control Room</div>
          <h1>Manage client access like a luxury studio.</h1>
          <p class="hero-copy">
            Onboard WhatsApp numbers, control who can use the bot, and manage credits from one clean dashboard.
          </p>
          <div class="stats">
            <article class="stat-card">
              <p class="stat-label">Total Clients</p>
              <p class="stat-value">{total_clients}</p>
            </article>
            <article class="stat-card">
              <p class="stat-label">Active Clients</p>
              <p class="stat-value">{active_clients}</p>
            </article>
            <article class="stat-card">
              <p class="stat-label">Inactive Clients</p>
              <p class="stat-value">{inactive_clients}</p>
            </article>
            <article class="stat-card">
              <p class="stat-label">Credits Live</p>
              <p class="stat-value">{total_credits}</p>
            </article>
          </div>
        </section>

        <section class="layout">
          <div class="panel">
            <div class="panel-inner">
              <h2>Add or update a client</h2>
              <p class="panel-copy">
                Save a WhatsApp number, choose whether access is active, and set the available credits for that client.
              </p>
              <form method="post" action="/admin/clients?admin_key={admin_key}">
                <div class="field">
                  <label for="name">Client Name</label>
                  <input id="name" type="text" name="name" placeholder="Client name" required>
                </div>
                <div class="field">
                  <label for="phone_number">WhatsApp Number</label>
                  <input id="phone_number" type="text" name="phone_number" placeholder="whatsapp:+9198xxxxxxx" required>
                  <p class="field-hint">Use full format with no spaces, for example: whatsapp:+919876543210</p>
                </div>
                <div class="field">
                  <label for="remaining_credits">Remaining Credits</label>
                  <input id="remaining_credits" type="number" name="remaining_credits" min="0" value="10" required>
                </div>
                <div class="field">
                  <label for="status">Status</label>
                  <select id="status" name="status">
                    <option value="active">active</option>
                    <option value="inactive">inactive</option>
                  </select>
                </div>
                <button type="submit">Save Client</button>
              </form>
            </div>
          </div>

          <div class="panel">
            <div class="panel-inner table-wrap">
              <div class="table-header">
                <div>
                  <h2>Client Access List</h2>
                  <p class="table-note">Every onboarded WhatsApp number appears here with status and remaining credits.</p>
                </div>
              </div>
              <div class="table-shell">
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
              </div>
            </div>
          </div>
        </section>
      </div>
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
