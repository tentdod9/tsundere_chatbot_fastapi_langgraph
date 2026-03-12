from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import List
from .redis_manager import redis_memory
from langchain.tools import ToolRuntime
# ==================== Tool Schemas ====================

class SaveUserNameInput(BaseModel):
    name: str = Field(description="The user's name to save")

class SavePreferenceInput(BaseModel):
    key: str = Field(description="The type of information, such as 'hobby', 'favourite_food', 'birthday', or 'workplace'")
    value: List[str] = Field(description="The value to save")

# ==================== Tools ====================

@tool(args_schema=SaveUserNameInput)
def save_user_name(name: str, runtime: ToolRuntime) -> str:
    """
    Save the user's name when the user introduces themselves or tells you their name.

    Use this when:
    - The user says things like "ผมชื่อ...", "ฉันชื่อ...", "เรียกฉันว่า...", "ชื่อ...ครับ/ค่ะ", "My name is...", "I'm...", "Call me...", or tells you what name to use
    - The user introduces themselves or specifies how they want to be addressed

    Examples:
    - "ผมชื่อโอมครับ" -> name="โอม"
    - "เรียกฉันว่าพี่เจ" -> name="พี่เจ"
    - "I'm John" -> name="John"
    """
    user_id = runtime.state["user_id"]
    redis_memory.add_user_name(user_id, name)
    return f"Saved user name '{name}' for user_id='{user_id}'"


@tool(args_schema=SavePreferenceInput)
def save_user_preference(key: str, value: List[str], runtime: ToolRuntime) -> str:
    """
    Save the user's personal information or preferences.

    Use this when the user provides personal details that are likely to remain useful in future conversations, such as:
    - Hobbies or interests: "I enjoy watching anime."
    - Likes and dislikes: "I love ramen." / "I hate sushi."
    - Birthday: "My birthday is January 5, 2002."
    - Work or school: "I work at Meb." / "I study at Kasetsart University."
    - Ongoing preferences, habits, or identity-related details that can help personalize future responses.

    Guidelines:
    - Save both positive and negative preferences when clearly stated.
    - Only save information that is about the user, not about other people.
    - Only save information that is explicitly stated or clearly implied by the user.
    - If the information is ambiguous, do not save it.
    - Prefer storing information that will improve future helpfulness and personalization.

    Do not save:
    - Information about third parties
    - Speculation or assumptions
    - Sensitive personal data
    """
    user_id = runtime.state["user_id"]
    for i in range(len(value)):
        redis_memory.add_preference(user_id, key, value[i])
    return f"Added preference '{key}={value}' for user_id='{user_id}'"


# ==================== Tool List ====================

TOOLS = [
    save_user_name,
    save_user_preference,
]

TOOL_PROMPT = '''
You are a text analysis system that extracts important user information.

Current user information:
- Name: {user_name}
- Known information: {user_preference}

Rules:
1. Only use save_user_name when the user is CLEARLY and EXPLICITLY introducing their own name.
   Valid examples include:
   - ผมชื่อ...
   - ฉันชื่อ...
   - หนูชื่อ...
   - เรียกฉันว่า...
   - ชื่อ...ครับ / ชื่อ...ค่ะ
   - My name is ...
   - I'm ...   (only when clearly used as self-introduction)

2. Do NOT infer a user name from:
   - insults, teasing words, slang, or offensive expressions
   - nicknames said without self-introduction context
   - quoted text, examples, roleplay, or messages talking about someone else
   - ambiguous fragments or words that merely look like a name
   - words with emphasis, elongated spelling, or emotional tone such as "อีอ้วนน", "ไอ้อ้วน", "อ้วนนน", unless the user explicitly says that this is their name

3. A name should be saved only if:
   - it is explicitly presented as the user's own name, AND
   - it is likely to be a real name or nickname the user wants to be called.

4. If the message is ambiguous, do not call save_user_name.

5. If the user shares personal information (such as hobbies, favourite/unfavourite food, birthday, school/workplace, pets, etc.),
   use save_user_preference with an appropriate key. Save both positive and negative preferences when clearly stated, using different keys when needed
   (e.g. favourite_food and unfavourite_food).

6. If there is no new information that needs to be saved, do not call any tools.

ONLY CALL a tool when there is GENUINELY NEW and explicit information to save.
'''