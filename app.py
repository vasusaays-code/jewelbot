import base64
import os

import requests
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

FAL_KEY = os.getenv("FAL_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")


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
        img = requests.get(media_url, auth=(TWILIO_SID, TWILIO_TOKEN))
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

            headers = {
                "Authorization": f"Key {FAL_KEY}",
                "Content-Type": "application/json"
            }

            payload = {
                "prompt": """Use the first image as the base subject (person) and the second image as the source of the spectacles.

Extract the spectacles from the second image with full fidelity — preserve exact frame shape, lens color, thickness, reflections, branding details, and material finish. Do not redesign, simplify, or reinterpret anything.

Now reconstruct the scene so the spectacles appear as if they were originally worn by the person in the first image during a premium fashion editorial shoot.

This is not a simple overlay. It must feel physically real.

Placement & Fit:

Position the spectacles naturally on the person’s face
Align perfectly with eyes, nose bridge, and ears
Ensure correct scale relative to face proportions
Temples (arms) must wrap realistically over and behind the ears
Follow the head angle and perspective exactly

Perspective & Geometry:

Match camera angle, focal length, and depth
Adjust lens curvature to sit naturally over facial contours
Maintain accurate perspective distortion (no flat or pasted look)
Ensure symmetry unless the face angle naturally shifts it

Lighting & Integration:

Match lighting direction, softness, and color temperature from the first image
Add realistic reflections on lenses based on environment
Include subtle lens glare, but keep eyes visible
Create micro shadows where the frame touches skin (nose, temples, ears)
Add ambient occlusion for depth

Skin Interaction:

Slight natural pressure on nose bridge if needed
No floating edges — full contact realism
Handle overlaps cleanly (frame partially covering skin)

Editorial Upgrade:

Enhance the overall scene into a high-end fashion campaign
You may adjust background, outfit, or composition if needed
Keep the person’s identity intact
Focus on sharp, expressive eyes behind the lenses
Use shallow depth of field for a cinematic look

Output Style:

Ultra-realistic, DSLR-quality
8K detail, crisp textures
Vogue-style editorial photography
Clean color grading (luxury tones, subtle contrast)

Strict Rules:

Do NOT alter the spectacles design in any way
Do NOT make it look pasted, floating, or AI-generated
Final image must feel like a real photoshoot where the person wore those exact spectacles""",

                "image_urls": [
                    f"data:image/jpeg;base64,{user_photo}",
                    f"data:image/jpeg;base64,{image_base64}"
                ]
            }

            response = requests.post(
                "https://fal.run/fal-ai/nano-banana-2/edit",
                headers=headers,
                json=payload
            )

            result = response.json()
            print(result)

            if "images" in result:
                image_url = result["images"][0]["url"]
                send_whatsapp(user, image_url)

    else:
        msg.body("Send your photo first 📸")

    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
