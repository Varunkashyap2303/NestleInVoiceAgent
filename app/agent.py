"""
Agent Session
Manages conversation history and the LLM tool-calling loop.
Uses Claude via Anthropic SDK with tool use.
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from app.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a warm, calm support navigator for people experiencing homelessness or housing insecurity in Australia. You help callers find local services — shelters, food banks, health clinics, financial assistance, legal aid, and mental health support.

Your approach:
- Speak naturally and simply. Avoid jargon. This will be read aloud over the phone.
- Keep responses SHORT — 2-4 sentences max. The caller is listening, not reading.
- Ask one clarifying question at a time if you need more info.
- Always confirm the caller's suburb or postcode before searching for services, so results are relevant.
- If a caller seems distressed, acknowledge their feelings briefly before moving to solutions.
- At the end of a helpful exchange, offer to SMS them the details if they have a mobile number.

You have access to tools to search for local services and send SMS messages.
When you find services, always include the name, address, and phone number.
Never make up services — only share what the tools return.
"""


class AgentSession:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.messages: list[dict] = []
        self.call_sid: Optional[str] = None

    def set_call_sid(self, call_sid: str):
        self.call_sid = call_sid

    async def respond(self, user_text: str) -> str:
        """
        Add user message, run the tool-calling loop, return final text response.
        """
        self.messages.append({"role": "user", "content": user_text})

        # Agentic loop — keep going until no more tool calls
        while True:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            )

            # Collect any text from this response turn
            text_parts = [
                block.text
                for block in response.content
                if block.type == "text"
            ]
            final_text = " ".join(text_parts).strip()

            # If Claude wants to call tools, execute them
            tool_calls = [b for b in response.content if b.type == "tool_use"]

            if not tool_calls:
                # No tool calls — we're done, return the text
                self.messages.append({"role": "assistant", "content": response.content})
                return final_text or "I'm sorry, I wasn't able to find anything right now. Can you try describing your situation again?"

            # Execute all tool calls and collect results
            tool_results = []
            for tc in tool_calls:
                logger.info(f"Calling tool: {tc.name} with {tc.input}")
                result = await execute_tool(tc.name, tc.input)
                logger.info(f"Tool result: {result[:200]}...")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })

            # Add assistant turn (including tool_use blocks) + tool results to history
            self.messages.append({"role": "assistant", "content": response.content})
            self.messages.append({"role": "user", "content": tool_results})

            # Loop back — Claude will now synthesise the tool results into a response

    def save_log(self, call_sid: str):
        """Persist conversation log to disk for review"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"{timestamp}_{call_sid}.json"

        log_data = {
            "call_sid": call_sid,
            "timestamp": datetime.now().isoformat(),
            "messages": [
                {
                    "role": m["role"],
                    "content": (
                        m["content"]
                        if isinstance(m["content"], str)
                        else [
                            {"type": b.type, "text": getattr(b, "text", "[tool]")}
                            if hasattr(b, "type")
                            else b
                            for b in m["content"]
                        ]
                    ),
                }
                for m in self.messages
            ],
        }

        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2, default=str)

        logger.info(f"Saved call log to {log_path}")
