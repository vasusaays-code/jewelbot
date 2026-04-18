# jewelbot

Small Flask webhook for a WhatsApp-based professional jewelry shoot flow using Twilio and Fal.

## Setup

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and add your real keys.
4. Run the app:

```bash
python app.py
```

The webhook endpoint is `/bot`.

## Bot Flow

1. User sends one jewelry image on WhatsApp.
2. The bot identifies the type of jewelry in the image.
3. The bot generates a luxury editorial-style professional model shoot featuring that exact item.
4. The result image is sent back on WhatsApp.

## Deploy on Render

1. Push this repo to GitHub.
2. In Render, create a new `Web Service` from the GitHub repo.
3. Use these settings:

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

4. Add these environment variables in Render:

```text
FAL_KEY
TWILIO_SID
TWILIO_TOKEN
```

5. After Render gives you a public URL, set your Twilio WhatsApp webhook to:

```text
https://your-service-name.onrender.com/bot
```

For testing, Render's free plan is fine. For better reliability later, move to a paid plan.
