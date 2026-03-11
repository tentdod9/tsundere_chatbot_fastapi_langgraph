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
    try:
        return redis_memory.get_session_list(user_id)
    except:
        return[{}]
    
@app.get("/sessions/detail")
async def get_sessions_detail(user_id: str, thread_id:str)-> Tuple[List[Dict], float]:
    try:
        return redis_memory.get_session_info(user_id, thread_id)
    except:
        return [{}], 0.0
    
@app.post("/graph")
async def chat_bot(user_input: str, user_id: str, thread_id:str) -> Tuple[str, float]:
    output_message, affection_score = call_graph(user_input, user_id, thread_id)
    redis_memory.add_message(user_id, thread_id, user_input, output_message)
    redis_memory.add_affection_score(user_id, thread_id, affection_score)
    redis_memory.add_session_list(user_id, thread_id, user_input)
    return output_message, affection_score