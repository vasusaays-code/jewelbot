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

## Client Access Control

The bot now supports:

1. allowlisted client WhatsApp numbers only
2. active/inactive client status
3. remaining credit limits per client
4. a small admin dashboard for onboarding and updating clients

### Admin Setup

Add this environment variable:

```text
ADMIN_API_KEY
```

Then open:

```text
https://your-service-name.onrender.com/admin?admin_key=YOUR_ADMIN_API_KEY
```

From there you can:

1. add a client name
2. add the client's WhatsApp number in `whatsapp:+<countrycode><number>` format
3. set remaining credits
4. activate or deactivate access

### How Credits Work

1. Each successful generation request consumes 1 credit.
2. If generation fails, the credit is automatically refunded.
3. If a client has 0 credits, the bot blocks access and asks them to contact support.

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
ADMIN_API_KEY
```

5. After Render gives you a public URL, set your Twilio WhatsApp webhook to:

```text
https://your-service-name.onrender.com/bot
```

For testing, Render's free plan is fine. For better reliability later, move to a paid plan.

Important:

1. This version uses SQLite by default.
2. On Render free instances without a persistent disk, onboarded clients and credits can reset after restarts or redeploys.
3. For production, move the client database to a persistent disk or an external database.
