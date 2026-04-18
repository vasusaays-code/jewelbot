import base64
import logging
import os
import threading

import requests
from flask import Flask, jsonify, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

load_dotenv()

FAL_KEY = os.getenv("FAL_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")

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

def send_whatsapp(to, image_url):
    get_twilio_client().messages.create(
        from_='whatsapp:+14155238886',
        to=to,
        body="✨ Done!",
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
            send_whatsapp_text(
                user,
                "Professional shoot create avvaledu. Konchem sepu tarvata malli try cheyandi.",
            )
            return

        send_whatsapp(user, images[0]["url"])
    except Exception:
        app.logger.exception("Editorial shoot generation failed for %s", user)
        send_whatsapp_text(
            user,
            "Professional shoot generate cheyyaledu. Konchem sepu tarvata malli try cheyandi.",
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


@app.route("/bot", methods=["POST"])
def bot():
    resp = MessagingResponse()
    msg = resp.message()

    if not FAL_KEY or not TWILIO_SID or not TWILIO_TOKEN:
        msg.body("Server configuration is incomplete. Please contact support.")
        return str(resp)

    media_url = request.values.get("MediaUrl0")
    user = request.values.get("From")

    if media_url:
        # download image
        img = requests.get(media_url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=30)
        img.raise_for_status()
        image_bytes = img.content
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        msg.body("⏳ Creating professional jewelry shoot...")
        thread = threading.Thread(
            target=process_editorial_shoot,
            args=(user, image_base64),
            daemon=True,
        )
        thread.start()

    else:
        msg.body("Jewellery image send cheyandi 💎")

    return str(resp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
