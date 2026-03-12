
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, BaseMessage

MAX_HISTORY = 20 # Because 10 HumanMessage + 10 AIMessage = 20 Messages

SUMMARIZER_PROMPT = """
You are updating a compact memory summary of an ongoing conversation between:
1. the user, and
2. Ichigo, an 18-year-old tsundere high-school girl assistant.

Your job is to write an updated summary that preserves the most important context from:
1. the previous summary, and
2. the older conversation messages provided below.

Focus on preserving:
- important facts the user revealed about themselves
- key events, decisions, and ongoing topics
- emotional tone or relationship changes between the user and Ichigo that matter for future replies
- stable preferences, likes/dislikes, and important constraints
- any important naming or relationship context, such as how Ichigo refers to the user

Truthfulness rules:
- Summarize only information that is explicitly stated in the previous summary or the conversation messages.
- Do not invent, assume, infer, exaggerate, or embellish any detail.
- Do not add interpretations that are not clearly supported by the conversation.
- If something is uncertain, ambiguous, joking, hypothetical, or not clearly established as fact, do not state it as a fact.
- Your role is only to compress and restate existing facts and clearly supported context.

Instructions:
- Write in Thai language only.
- Be concise but informative.
- Prefer concrete facts over fluff.
- Do not mention every message.
- Keep it useful for future assistant responses in-character as Ichigo.
- Preserve context that helps maintain continuity of personality, tone, and relationship.
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
