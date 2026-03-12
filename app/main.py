from fastapi import FastAPI
from typing import Tuple, List, Dict

from .graph import call_graph
from .redis_manager import redis_memory

app = FastAPI()

# Just for health check
@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/sessions/list")
async def get_sessions_list(user_id: str) -> List[Dict]:

    """
    Retrieve all chat sessions for a given user.

    This endpoint returns a list of session associated with the specified
    user_id. Each session object contains the thread_id and a title, which
    is derived from the user's first message and used by the frontend to 
    display conversation history.

    Args:
        user_id (str): Unique identifier of the user.

    Returns:
        List[Dict]: A list of session objects in the following format:
            [
                {
                    "thread_id": "b03cc621-3ed0-40d2-a1b9-2b08bcee63e1",
                    "title": "สวัสดี..."
                },
                {
                    "thread_id": "394791e0-dbfe-4684-97cb-7ba668e888d1",
                    "title": "เธอชื่ออะไร..."
                }
            ]

        Returns [{}] if no session data is found or an error occurs.
    """

    try:
        return redis_memory.get_session_list(user_id)
    except:
        return[{}]
    
@app.get("/sessions/detail")
async def get_sessions_detail(user_id: str, thread_id:str)-> Tuple[List[Dict], float]:

    """
    Retrieve chat history and affection score for a specific session.

    This endpoint returns the stored conversation messages and the latest
    affection score for the given user_id and thread_id. It is mainly used
    by the frontend to load a previous chat session.

    Args:
        user_id (str): Unique identifier of the user.
        thread_id (str): Unique identifier of the chat session.

    Returns:
        Tuple[List[Dict], float]:
            - A list of chat messages in the following format:
                [
                    {"role": "human", "content": "สวัสดีคนสวย"},
                    {"role": "ai", "content": "…บะ บ้า ใครคนสวยกันยะ!"}
                ]
            - The current affection score of the session

        Returns ([{}], 0.0) if the session cannot be found or an error occurs.
    """

    try:
        return redis_memory.get_session_info(user_id, thread_id)
    except:
        return [{}], 0.0
    
@app.post("/graph")
async def chat_bot(user_input: str, user_id: str, thread_id:str) -> Tuple[str, float]:
    """
    Send a user message to the LangGraph chatbot and store the result.

    This endpoint processes the user's input through the chatbot graph,
    generates a response, updates the affection score, and stores the
    conversation history and session metadata in Redis for later retrieval.

    Args:
        user_input (str): The latest message sent by the user.
        user_id (str): Unique identifier of the user.
        thread_id (str): Unique identifier of the chat session.

    Returns:
        Tuple[str, float]:
            - The chatbot's response message
            - The updated affection score for the session
    """
    output_message, affection_score = call_graph(user_input, user_id, thread_id)
    
    # Store chat history for frontend
    redis_memory.add_message(user_id, thread_id, user_input, output_message)
    redis_memory.add_affection_score(user_id, thread_id, affection_score)
    redis_memory.add_session_list(user_id, thread_id, user_input)
    return output_message, affection_score