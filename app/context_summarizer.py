
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, BaseMessage

SUMMARIZER_PROMPT = f"""
You are updating a compact memory summary of an ongoing conversation.

Your job is to write an updated summary that preserves the most important context from:
1. the previous summary, and
2. the older conversation messages provided below.

Focus on preserving:
- important facts the user revealed about themselves
- key events, decisions, and ongoing topics
- emotional tone or relationship changes that matter for future replies
- stable preferences, likes/dislikes, and important constraints

Instructions:
- Write in Thai Language.
- Be concise but informative.
- Prefer concrete facts over fluff.
- Do not mention every message.
- Keep it useful for future assistant responses.
- Output only the summary text.
"""

SUMMARIZER_INPUT = """
Previous summary:
{previous_summary}

Older conversation messages:
{conversation_text}

Updated summary:
"""

def format_message(msg: BaseMessage) -> str:
    if msg.type == "human":
        return f"User: {msg.content}"
    elif msg.type == "ai":
        return f"Assistant: {msg.content}"
    elif msg.type == "system":
        return f"System: {msg.content}"
    else:
        return f"{msg.type}: {msg.content}"
