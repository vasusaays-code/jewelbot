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

TRYON_PROMPT = """Use the first image as the base subject (person) and the second image as the source of the jewelry item or accessory.

Extract the jewelry or accessory from the second image with full fidelity — preserve the exact design, shape, color, metal finish, stones, reflections, branding details, and material finish. Do not redesign, simplify, or reinterpret anything.

Now reconstruct the scene so the jewelry or accessory appears as if it were originally worn by the person in the first image during a premium fashion editorial shoot.

This is not a simple overlay. It must feel physically real.

Placement & Fit:

Position the jewelry or accessory naturally on the correct part of the body
Ensure correct scale relative to the person's proportions
Align perfectly with the body part it belongs to
Follow the person's pose, head angle, and perspective exactly

Perspective & Geometry:

Match camera angle, focal length, and depth
Maintain accurate perspective distortion (no flat or pasted look)
Ensure placement feels physically believable and consistent with the person's pose

Lighting & Integration:

Match lighting direction, softness, and color temperature from the first image
Add realistic reflections based on the jewelry material and environment
Create micro shadows where the item touches skin, hair, or clothing
Add ambient occlusion for depth

Skin Interaction:

No floating edges — full contact realism
Handle overlaps cleanly with skin, hair, or clothing

Editorial Upgrade:

Enhance the overall scene into a high-end fashion campaign
You may adjust background, outfit, or composition if needed
Keep the person’s identity intact
Use shallow depth of field for a cinematic look

Output Style:

Ultra-realistic, DSLR-quality
8K detail, crisp textures
Vogue-style editorial photography
Clean color grading (luxury tones, subtle contrast)

Strict Rules:

Do NOT alter the jewelry or accessory design in any way
Do NOT make it look pasted, floating, or AI-generated
Final image must feel like a real photoshoot where the person wore that exact item naturally"""


def get_twilio_client():
    if not TWILIO_SID or not TWILIO_TOKEN:
        raise RuntimeError("Missing TWILIO_SID or TWILIO_TOKEN environment variables.")
    return Client(TWILIO_SID, TWILIO_TOKEN)

# 🧠 store user images temporarily
user_memory = {}


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


def process_tryon(user, user_photo, reference_image):
    headers = {
        "Authorization": f"Key {FAL_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": TRYON_PROMPT,
        "image_urls": [
            f"data:image/jpeg;base64,{user_photo}",
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
        app.logger.info("Fal response for %s: %s", user, result)

        images = result.get("images") or []
        if not images or not images[0].get("url"):
            send_whatsapp_text(
                user,
                "Try-on complete avvaledu. Konchem sepu tarvata malli try cheyandi.",
            )
            return

        send_whatsapp(user, images[0]["url"])
    except Exception:
        app.logger.exception("Try-on generation failed for %s", user)
        send_whatsapp_text(
            user,
            "Try-on generate cheyyaledu. Konchem sepu tarvata malli try cheyandi.",
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

        # 👉 FIRST IMAGE (user photo)
        if user not in user_memory:
            user_memory[user] = image_base64
            msg.body("📸 late enduku?jewellery image kuda send cheyandi.")
            return str(resp)

        # 👉 SECOND IMAGE (jewellery)
        else:
            user_photo = user_memory[user]
            del user_memory[user]

            msg.body("⏳ Creating try-on...")
            thread = threading.Thread(
                target=process_tryon,
                args=(user, user_photo, image_base64),
                daemon=True,
            )
            thread.start()

    else:
        msg.body("Send your photo first 📸")

    return str(resp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
