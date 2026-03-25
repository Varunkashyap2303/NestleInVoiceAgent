"""
Deepgram STT Client
Streams audio to Deepgram and fires a callback when the user finishes speaking.
Uses Deepgram's Nova-2 model with endpointing for natural turn detection.
"""

import os
import base64
import asyncio
import logging
from typing import Callable, Awaitable, Optional

import websockets
import json

logger = logging.getLogger(__name__)

DEEPGRAM_STT_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en-AU"          # Australian English
    "&encoding=mulaw"          # Twilio sends μ-law audio
    "&sample_rate=8000"
    "&channels=1"
    "&punctuate=true"
    "&endpointing=500"         # ms of silence before firing final transcript
    "&utterance_end_ms=1500"   # Treat as end of utterance after 1.5s silence
    "&interim_results=true"
    "&smart_format=true"
)


class DeepgramSTT:
    def __init__(self):
        self.api_key = os.environ["DEEPGRAM_API_KEY"]
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._on_transcript: Optional[Callable[[str], Awaitable[None]]] = None
        self._current_utterance = ""

    async def connect(self, on_transcript: Callable[[str], Awaitable[None]]):
        """Open WebSocket to Deepgram and start listening for transcripts."""
        self._on_transcript = on_transcript

        self._ws = await websockets.connect(
            DEEPGRAM_STT_URL,
            extra_headers={"Authorization": f"Token {self.api_key}"},
        )
        logger.info("Deepgram STT connected")

        # Start background task to receive transcripts
        self._listen_task = asyncio.create_task(self._listen())

    async def send_audio(self, payload_b64: str):
        """
        Forward base64-encoded μ-law audio from Twilio to Deepgram.
        Deepgram expects raw bytes.
        """
        if self._ws:
            audio_bytes = base64.b64decode(payload_b64)
            await self._ws.send(audio_bytes)

    async def _listen(self):
        """Background task: receive and process Deepgram events."""
        try:
            async for message in self._ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "Results":
                    alt = data.get("channel", {}).get("alternatives", [{}])[0]
                    transcript = alt.get("transcript", "").strip()
                    is_final = data.get("is_final", False)
                    speech_final = data.get("speech_final", False)

                    if transcript and is_final:
                        self._current_utterance = transcript

                    # speech_final fires after endpointing detects end of utterance
                    if speech_final and self._current_utterance:
                        text = self._current_utterance
                        self._current_utterance = ""
                        logger.info(f"Final transcript: {text!r}")
                        if self._on_transcript:
                            await self._on_transcript(text)

                elif msg_type == "UtteranceEnd":
                    # Backup trigger if speech_final didn't fire
                    if self._current_utterance:
                        text = self._current_utterance
                        self._current_utterance = ""
                        if self._on_transcript:
                            await self._on_transcript(text)

                elif msg_type == "Error":
                    logger.error(f"Deepgram error: {data}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("Deepgram connection closed")
        except Exception as e:
            logger.error(f"Deepgram listener error: {e}")

    async def close(self):
        """Gracefully close the Deepgram connection."""
        if self._ws:
            try:
                # Send close frame
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
            await self._ws.close()

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        logger.info("Deepgram STT closed")
