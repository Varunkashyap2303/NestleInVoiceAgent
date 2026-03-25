"""
Local test harness — run the agent loop from your terminal
without needing a real phone number or Twilio connection.

Usage:
    python tests/test_agent_local.py

Set ANTHROPIC_API_KEY in your .env before running.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.agent import AgentSession


async def main():
    print("\n" + "=" * 60)
    print("  Support Navigator — Local Test")
    print("  Type your message. Press Ctrl+C to exit.")
    print("=" * 60 + "\n")

    session = AgentSession()
    session.set_call_sid("local-test-001")

    print("Agent: Hello, you've reached the Support Navigator. "
          "I'm here to help you find local services. "
          "What do you need help with today?\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSession ended.")
            break

        if not user_input:
            continue

        print("Agent: [thinking...]\r", end="", flush=True)
        response = await session.respond(user_input)
        print(f"Agent: {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
