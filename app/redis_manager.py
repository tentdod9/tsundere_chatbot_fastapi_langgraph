import redis
import json
from typing import Optional, Dict, List, Tuple

class UserPreferenceMemory:
    def __init__(self, redis_url: str):
        self.store = redis.Redis.from_url(redis_url, decode_responses=True)
        self.namespace_prefix = "tsundere"

    def _preferences_key(self, user_id: str) -> str:
        return f"{self.namespace_prefix}:users:{user_id}:preferences"
    
    def _user_name_key(self, user_id: str) -> str:
        return f"{self.namespace_prefix}:users:{user_id}:user_name"
    
    def _sessions_with_thread_key(self, user_id: str, thread_id: str) -> str:
        return f"{self.namespace_prefix}:users:{user_id}:sessions:{thread_id}"
    
    def _sessions_list_key(self, user_id: str) -> str:
        return f"{self.namespace_prefix}:users:{user_id}:sessions"
    
    # def _sessions_list_key(self, user_id: str) -> str:
    #     return f"{self.namespace_prefix}:users:{user_id}:sessions"

    def add_preference(self, user_id: str, key: str, value: str) -> None:
        """
        Add a preference value.
        - If the key does not exist, create a new list with the value.
        - If the key already exists, append the value to the list.
        """
        redis_key = self._preferences_key(user_id)
        existing = self.store.hget(redis_key, key)

        if existing is None:
            values = [value]
        else:
            try:
                parsed = json.loads(existing)
                if isinstance(parsed, list):
                    values = parsed
                else:
                    values = [str(parsed)]
            except json.JSONDecodeError:
                values = [existing]

            values.append(value)

        self.store.hset(redis_key, key, json.dumps(values, ensure_ascii=False))

    def add_user_name(self, user_id: str, user_name: str) -> None:
        """
        Add a user name.
        """
        redis_key = self._user_name_key(user_id)

        self.store.hset(redis_key, "user_name", json.dumps([user_name], ensure_ascii=False))

    def load_preference(self, user_id: str, key: str) -> Optional[List[str]]:
        """
        Load a single preference as a list.
        Returns None if not found.
        """
        redis_key = self._preferences_key(user_id)
        value = self.store.hget(redis_key, key)

        if value is None:
            return None

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            return [str(parsed)]
        except json.JSONDecodeError:
            return [value]

    def load_all_preferences(self, user_id: str) -> Dict[str, List[str]]:
        """
        Load all preferences for a user.
        Every field is returned as list[str].
        """
        redis_key = self._preferences_key(user_id)
        raw_data = self.store.hgetall(redis_key)

        parsed_data = {}
        for key, value in raw_data.items():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    parsed_data[key] = parsed
                else:
                    parsed_data[key] = [str(parsed)]
            except json.JSONDecodeError:
                parsed_data[key] = [value]

        return parsed_data
    
    def load_user_name(self, user_id: str) -> str:
        """
        Load a user name.
        """
        redis_key = self._user_name_key(user_id)
        
        return self.store.hget(redis_key, "user_name")[0]
    
    def add_message(self, user_id: str, thread_id: str,  human_message: str, ai_message: str):
        """
        Add conversation messages history corresponding to user_id and thread_id.
        """
        redis_key = self._sessions_with_thread_key(user_id, thread_id)
        existing = self.store.hget(redis_key, "messages")

        new_messages = [
            {"role": "human", "content": human_message},
            {"role": "ai", "content": ai_message},
        ]
        
        if existing is None:
            values = new_messages
        else:
            try:
                parsed = json.loads(existing)

                if isinstance(parsed, list):
                    values = parsed
                else:
                    values = []
            except json.JSONDecodeError:
                values = []

            values.extend(new_messages)

        self.store.hset(redis_key, "messages", json.dumps(values, ensure_ascii=False))
        

    def add_affection_score(self, user_id: str, thread_id: str, affection_score: float):
        """
        Add an affection score corresponding to user_id and thread_id.
        """
        redis_key = self._sessions_with_thread_key(user_id, thread_id)
        self.store.hset(redis_key, "affection_score", affection_score)

    def get_session_info(self, user_id: str, thread_id: str) -> Tuple[List[Dict], float]:
        """
        Get conversation messages history and an affection score corresponding to user_id and thread_id.
        """
        redis_key = self._sessions_with_thread_key(user_id, thread_id)
        messages_history = json.loads(self.store.hget(redis_key, "messages"))
        affection_score = self.store.hget(redis_key, "affection_score")
        
        return messages_history, affection_score
    
    def add_session_list(self, user_id: str, thread_id: str, title: str):
        """
        Add brief session data to session_list:

        {user_id}:sessions
        [
            {
                "thread_id": "d4a0fc3b-498e-486e-93b3-c57eb169c0c4",
                "title": "สอนเขียน Python หน่อย...",
            },
            {
                "thread_id": "07058a1c-b09a-40a7-8c1a-30412a949ca2",
                "title": "ตำไทยกับตำปูปลาร้าต่างกันยังไง...",
            }
        ]
        """
        redis_key = self._sessions_list_key(user_id)
        existing = self.store.hget(redis_key, "sessions")

        new_session = [{
            "thread_id": thread_id,
            "title": title,
        }]

        if existing is not None:
            existing = json.loads(existing)
            for session in existing:
                if session["thread_id"] == thread_id:
                    return
            existing.extend(new_session)
        else:
            existing = new_session
        
        self.store.hset(redis_key, "sessions", json.dumps(existing, ensure_ascii=False))

    
    def get_session_list(self, user_id: str) -> List[Dict]:
        """
        Return all sessions list corresponding to user_id
        """
        redis_key = self._sessions_list_key(user_id)
        return json.loads(self.store.hget(redis_key, "sessions"))
    
   


    
redis_memory = UserPreferenceMemory("redis://redis:6379")   
if __name__ == "__main__":

    # redis_memory.add_session_list("admin4", "six", "ฉันชื่อเต็นท์ ชอบกินไอติม พิซซ่า ซูชิ และชอบดูอนิเมะ ออกกำลังกาย และอ่านนิยายวาย ฉันเกิดวันพุธ และชอบสีแดง")
    redis_memory.get_session_list("admin4")
    # redis_memory.get_session_info("admin4","four")
    # memory.add_preference("u123", "favourite_food", "ราเมง")
    # memory.add_preference("u123", "favourite_food", "ส้มตำ")

    # print(memory.load_preference("u123", "favourite_food"))
    # print(memory.load_all_preferences())