# Support Navigator — Voice Agent

A phone-based AI agent that helps people experiencing homelessness or housing insecurity find local services. Callers describe their needs in plain language and the agent responds with relevant services, addresses, and phone numbers — and can SMS the details to their phone.

## Architecture

```
Caller → Twilio (phone) → FastAPI server → Deepgram (STT)
                                         ↓
                                   Claude (agent + tools)
                                         ↓
                              [search_local_services]
                              [send_sms]
                              [get_crisis_lines]
                                         ↓
                                   TTS → Twilio → Caller hears response
```

## Quick Start

### 1. Install dependencies

```bash
cd voice-agent
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

You need accounts with:
- **Anthropic** — https://console.anthropic.com (for Claude)
- **Twilio** — https://twilio.com (for the phone number + audio streaming)
- **Deepgram** — https://deepgram.com (for speech-to-text, generous free tier)

### 3. Test locally without a phone

Run the agent in your terminal to verify everything works before connecting Twilio:

```bash
python tests/test_agent_local.py
```

### 4. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Expose your local server with ngrok

Twilio needs a public URL to send webhooks to. Use ngrok to expose your local server:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL — you'll use it in the next step.

### 6. Configure Twilio

1. Go to [Twilio Console](https://console.twilio.com)
2. Buy a phone number (or use an existing one)
3. Under **Voice & Fax → A Call Comes In**, set:
   - Webhook: `https://xxxx.ngrok.io/incoming-call`
   - Method: `HTTP POST`
4. Under **Call Status Changes**, set:
   - Webhook: `https://xxxx.ngrok.io/call-status`
5. Save. Call your Twilio number — you should hear the agent!

---

## Customising Services

Edit `resources/services.json` to add services for your region. Each entry:

```json
{
  "name": "Service Name",
  "categories": ["shelter"],          // see categories below
  "address": "123 Example St",
  "suburb": "Fitzroy",
  "postcode": "3065",
  "phone": "(03) 9999 0000",
  "hours": "Mon-Fri 9am-5pm",
  "accepts_walkins": true,
  "24_hour": false,
  "notes": "Optional extra info"
}
```

**Categories:** `shelter`, `food`, `health`, `mental_health`, `legal`, `financial`, `domestic_violence`, `substance_support`, `general`

---

## Connecting AskIzzy (recommended for production)

AskIzzy is Australia's largest social services directory with 360,000+ services.

1. Apply for API access: https://github.com/ask-izzy/ask-izzy
2. Add `ASKIZZY_API_KEY=...` to your `.env`

The agent will query AskIzzy first and fall back to your local database.

---

## Upgrading TTS to ElevenLabs

The default TTS uses Twilio's built-in Polly voices. For a warmer, more natural voice:

1. Create an ElevenLabs account: https://elevenlabs.io
2. Add to `.env`:
   ```
   TTS_PROVIDER=elevenlabs
   ELEVENLABS_API_KEY=...
   ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # or pick your own
   ```

---

## Deployment (production)

For a persistent deployment, use a cloud VM or platform:

**Railway (easiest):**
```bash
railway init
railway up
```
Set environment variables in the Railway dashboard.

**Fly.io:**
```bash
fly launch
fly secrets set ANTHROPIC_API_KEY=... TWILIO_ACCOUNT_SID=... # etc.
fly deploy
```

Update your Twilio webhook URL to the production URL.

---

## Call Logs

All conversations are saved to `logs/` as JSON files named `{timestamp}_{callSid}.json`. Review these to improve the agent's responses and identify gaps in your resource database.

---

## Project Structure

```
voice-agent/
├── app/
│   ├── main.py          # FastAPI server, Twilio webhooks, WebSocket handler
│   ├── agent.py         # AgentSession — LLM loop with tool calling
│   ├── tools.py         # Tool definitions + execution (search, SMS, crisis lines)
│   ├── stt.py           # Deepgram real-time STT client
│   └── tts.py           # TTS client (Polly or ElevenLabs)
├── resources/
│   └── services.json    # Local service database — edit this!
├── tests/
│   └── test_agent_local.py  # Terminal-based test harness
├── logs/                # Auto-created, stores call transcripts
├── .env.example         # Copy to .env and fill in keys
├── requirements.txt
└── README.md
```

---

## Roadmap (v2 ideas)

- [ ] Connect AskIzzy API for live national service search
- [ ] Add postcode-to-suburb resolution
- [ ] Dashboard to review call logs and flag gaps in coverage
- [ ] Multi-language support (Vietnamese, Arabic, Simplified Chinese)
- [ ] Warm transfer to a human worker for complex cases
- [ ] Intake form auto-completion via voice
