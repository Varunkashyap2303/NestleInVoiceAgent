"""
Voice Agent - Main server
Handles Twilio webhooks, orchestrates STT → LLM → TTS loop
"""

import os
import json
import asyncio
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from dotenv import load_dotenv

from app.agent import AgentSession
from app.stt import DeepgramSTT
from app.tts import TTSClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Support Navigator Voice Agent")


# ─────────────────────────────────────────────────────────────
# Twilio webhook — called when someone dials your number
# ─────────────────────────────────────────────────────────────

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """
    Twilio hits this endpoint when a call comes in.
    We respond with TwiML that opens a bi-directional audio stream
    back to our WebSocket endpoint.
    """
    host = request.headers.get("host", "localhost")
    protocol = "wss" if "localhost" not in host else "ws"

    response = VoiceResponse()
    response.say(
        "Hello, you've reached the Support Navigator. "
        "I'm here to help you find local services for housing, food, health, and more. "
        "Please describe what you need and I'll do my best to help.",
        voice="Polly.Joanna"
    )

    connect = Connect()
    connect.stream(url=f"{protocol}://{host}/audio-stream")
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def call_status(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
):
    """Twilio calls this when call status changes (completed, failed, etc.)"""
    logger.info(f"Call {CallSid} status: {CallStatus}")
    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────
# WebSocket — bi-directional audio stream with Twilio
# ─────────────────────────────────────────────────────────────

@app.websocket("/audio-stream")
async def audio_stream(websocket: WebSocket):
    """
    Twilio sends raw μ-law audio frames here.
    We pipe them to Deepgram for STT, then run the agent loop.
    """
    await websocket.accept()
    logger.info("WebSocket connection opened")

    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None

    stt = DeepgramSTT()
    tts = TTSClient()
    session = AgentSession()

    async def on_transcript(text: str):
        """Called by STT when user finishes speaking"""
        if not text.strip():
            return

        logger.info(f"User said: {text!r}")

        # Get agent response (may call tools internally)
        response_text = await session.respond(text)
        logger.info(f"Agent response: {response_text!r}")

        # Convert response to audio and send back via Twilio
        audio_b64 = await tts.synthesize(response_text)
        if audio_b64 and stream_sid:
            await send_audio(websocket, stream_sid, audio_b64)

    # Start Deepgram connection
    await stt.connect(on_transcript)

    try:
        async for raw_message in websocket.iter_text():
            msg = json.loads(raw_message)
            event = msg.get("event")

            if event == "connected":
                logger.info("Twilio stream connected")

            elif event == "start":
                call_sid = msg["start"]["callSid"]
                stream_sid = msg["start"]["streamSid"]
                logger.info(f"Stream started — call: {call_sid}")
                session.set_call_sid(call_sid)

            elif event == "media":
                # Forward audio payload to Deepgram
                payload = msg["media"]["payload"]
                await stt.send_audio(payload)

            elif event == "stop":
                logger.info("Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        await stt.close()
        logger.info(f"Session ended — call: {call_sid}")
        if call_sid:
            session.save_log(call_sid)


async def send_audio(websocket: WebSocket, stream_sid: str, audio_b64: str):
    """Send synthesized audio back to Twilio over the WebSocket"""
    message = {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": audio_b64},
    }
    await websocket.send_text(json.dumps(message))


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
