# chat_app.py
from dotenv import load_dotenv
load_dotenv(override=True)

import os
import chainlit as cl
from chainlit.input_widget import Switch
from claude.handler import handle as _claude_handle, clear_history

# ── Chainlit handlers ─────────────────────────────────────────────────────────
@cl.on_chat_start
async def on_start():
    cl.user_session.set("claude_history", [])

@cl.on_message
async def on_message(message: cl.Message):
    if message.content.strip().lower() in ("/clear", "clear history"):
        clear_history()
        await cl.Message(content="✅ Conversation history cleared. Starting fresh.").send()
        return
    await _claude_handle(message.content, message)
