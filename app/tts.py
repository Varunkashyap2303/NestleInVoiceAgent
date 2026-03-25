"""
TTS Client
Converts the agent's text response to base64-encoded μ-law audio
suitable for streaming back via Twilio.

Default: Twilio's built-in Polly TTS (no extra cost, easiest to set up).
Upgrade path: swap to ElevenLabs for a more natural voice.
"""

import os
import base64
import logging
import audioop
import io
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "twilio_polly")  # or "elevenlabs"


class TTSClient:
    async def synthesize(self, text: str) -> Optional[str]:
        """
        Convert text to base64-encoded μ-law audio (8kHz, mono).
        Returns None on failure.
        """
        if TTS_PROVIDER == "elevenlabs":
            return await self._elevenlabs(text)
        else:
            return await self._twilio_polly(text)

    # ─────────────────────────────────────────────────────────
    # ElevenLabs (higher quality, ~$0.30 per 1k chars)
    # ─────────────────────────────────────────────────────────

    async def _elevenlabs(self, text: str) -> Optional[str]:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

        if not api_key:
            logger.warning("No ELEVENLABS_API_KEY — falling back to Polly")
            return await self._twilio_polly(text)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_turbo_v2",
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                        "output_format": "pcm_16000",  # 16kHz PCM
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                pcm_16k = resp.content

            # Downsample 16kHz → 8kHz PCM, then convert to μ-law
            pcm_8k, _ = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)
            ulaw = audioop.lin2ulaw(pcm_8k, 2)
            return base64.b64encode(ulaw).decode("utf-8")

        except Exception as e:
            logger.error(f"ElevenLabs TTS failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # Twilio Polly (free with Twilio, via <Say> TwiML verb)
    # For the WebSocket stream we use Twilio's Media Stream TTS
    # endpoint as a lightweight alternative.
    # ─────────────────────────────────────────────────────────

    async def _twilio_polly(self, text: str) -> Optional[str]:
        """
        Use AWS Polly via a small helper endpoint.
        For simplicity in v1, we call a local synthesis endpoint
        or return None to trigger a TwiML redirect with <Say>.

        In practice for production: host a tiny endpoint that accepts
        text, calls boto3 polly.synthesize_speech(), resamples to 8kHz
        μ-law, and returns base64. See README for setup instructions.
        """
        polly_endpoint = os.getenv("POLLY_SYNTHESIS_URL")
        if not polly_endpoint:
            # If no Polly endpoint, return a sentinel so main.py
            # falls back to injecting a <Say> TwiML mid-call.
            logger.info("No POLLY_SYNTHESIS_URL set — caller will hear Twilio's built-in voice")
            return None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    polly_endpoint,
                    json={"text": text},
                    timeout=8.0,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("audio_b64")
        except Exception as e:
            logger.error(f"Polly synthesis failed: {e}")
            return None
