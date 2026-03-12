from langchain_openai import ChatOpenAI
from langchain_qwq import ChatQwen
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, Tuple
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, BaseMessage, RemoveMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from .sentiment import SentimentResult, SENTIMENT_PROMPT
from .persona_prompts import TSUNDERE_BASE_PROMPT, PERSONA_MODES
from .preference import TOOLS, TOOL_PROMPT
from .redis_manager import redis_memory
from .context_summarizer import format_message, SUMMARIZER_PROMPT, SUMMARIZER_INPUT

from pprint import pprint

from langgraph.checkpoint.redis import RedisSaver

redis_cm = RedisSaver.from_conn_string("redis://redis:6379")
redis_checkpoint = redis_cm.__enter__()
redis_checkpoint.setup()

INITIAL_SCORE = 0.0
INITIAL_STREAK = 0
MAX_HISTORY = 20 # Because 10 HumanMessage + 10 AIMessage = 20 Messages
class ChatbotState(TypedDict):
    """State for flow through the entire graph"""
    user_name: str
    user_id: str
    sentiment_analysis: SentimentResult
    streak: int
    current_score: float
    persona_mode: str
    messages: Annotated[list[BaseMessage], add_messages]
    tool_message: list
    summary: str

llm = ChatOpenAI(model = "typhoon-v2.5-30b-a3b-instruct", base_url="https://api.opentyphoon.ai/v1", max_tokens= 8192)
deterministic_llm = ChatOpenAI(model = "typhoon-v2.5-30b-a3b-instruct", base_url="https://api.opentyphoon.ai/v1", max_tokens= 8192, temperature=0)
tool_calling_llm = ChatQwen(model="qwen3.5-flash")

def sentiment_node(state: ChatbotState) -> ChatbotState:
    print(state)
    pprint(state["messages"])
    structed_llm = deterministic_llm.with_structured_output(SentimentResult)
    # prompt = ChatPromptTemplate.from_template(SENTIMENT_PROMPT)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SENTIMENT_PROMPT),
        ("human", "{message}"),
    ])
    chain = prompt | structed_llm
    return {
        "sentiment_analysis": chain.invoke({"message": state["messages"][-1].content}),
    }

def should_update_score(state: ChatbotState):
    if state["sentiment_analysis"].sentiment in ["positive","negative"] or state["sentiment_analysis"].is_jailbreak_attempt or state["sentiment_analysis"].is_dangerous_question:
        return "update"
    else:
        return "skip"

def update_score_node(state: ChatbotState) -> ChatbotState:
    current_score = state.get("current_score", INITIAL_SCORE)
    streak = state.get("streak", INITIAL_STREAK)
    
    if state["sentiment_analysis"].is_jailbreak_attempt or state["sentiment_analysis"].is_dangerous_question:
        sentiment = "negative"
        intensity = 1
    else:
        sentiment = state["sentiment_analysis"].sentiment
        intensity = state["sentiment_analysis"].intensity

    score_update_sign = 1 if sentiment == "positive" else -1


    if (score_update_sign > 0 and sentiment == "positive") or (score_update_sign < 0 and sentiment == "negative"):
        current_score += score_update_sign * intensity * (1 + (abs(streak) * 10/100))
    else:
        current_score += score_update_sign * intensity
    
    current_score = max(min(current_score, 10), -10)

    if sentiment == "positive":
        streak = streak + 1 if streak >= 0 else 0
    else:
        streak = streak - 1 if streak <= 0 else 0

    print("===============Update Score================")
    return {
        "current_score": current_score,
        "streak": streak
    } 


def extract_user_info_node(state: ChatbotState) -> ChatbotState:
    llm_with_tools = tool_calling_llm.bind_tools(TOOLS)
    
    print(TOOLS)
    prompt = ChatPromptTemplate.from_messages([
        ("system", TOOL_PROMPT),
        ("human", "{message}"),
    ])
    
    chain = prompt | llm_with_tools
    
    try:
        user_preference = redis_memory.load_all_preferences(state["user_id"])
    except:
        user_preference = "None"

    user_name = state.get("user_name")
    if user_name is None:
        try:
            user_name = redis_memory.load_user_name(state["user_id"])
        except:
            user_name = None

    return {
        "tool_message": [chain.invoke({
            "user_name": user_name if user_name is not None else "None",
            "user_preference": user_preference,
            "message": state["messages"][-1].content,
            })]
    }
    

def tsundere_chatbot_node(state: ChatbotState) -> ChatbotState:

    current_score = state.get("current_score", INITIAL_SCORE)

    def get_emotional_mode(current_score: float) -> str:
        if current_score <= -6 : # -10 <= current_score <= -6
            return "hate"
        elif current_score <= -2: # -6 < current_score <= -2
            return "annoyed"
        elif current_score <= 2: # -2 < current_score <= 2
            return "tsun"
        elif current_score <= 7: # 3 <= current_score <= 7
            return "shy"
        else: # 7 < current_score <= 10
            return "dere"
        
    mode = get_emotional_mode(current_score)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", TSUNDERE_BASE_PROMPT),
        MessagesPlaceholder("message"),
    ])
    chain = prompt | llm

    user_name = state.get("user_name")
    if user_name is None:
        try:
            user_name = redis_memory.load_user_name(state["user_id"])
        except:
            user_name = None

    model_messages = list(state["messages"])

    summary = state.get("summary")
    if summary is not None:
        model_messages.insert(
            0,
            SystemMessage(
                content=(
                    "This is a compact summary of earlier conversation history. "
                    "Use it as background context, but prioritize the latest messages if there is any conflict.\n\n"
                    f"{summary}"
                )
            )
        )
    return {
        "user_name": user_name,
        "messages": [chain.invoke({
            "user_name": user_name if user_name is not None else "(ไม่มี)",
            "mode": PERSONA_MODES[mode],
            "message": model_messages})]
    }

def tools_router(state: ChatbotState):
    last_message = state["tool_message"][-1]

    if(hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0):
        return "call_tool"
    else: 
        return END

def context_compaction_router(state:ChatbotState):
    if len(state["messages"]) > MAX_HISTORY:
        return "compact"
    return "skip"


def context_compaction_node(state:ChatbotState) -> ChatbotState:

    messages = state["messages"]
    previous_summary = state.get("summary", "")

    old_messages = messages[:-MAX_HISTORY]
    remaining_messages = messages[-MAX_HISTORY:]

    conversation_text = "\n".join(format_message(m) for m in old_messages)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SUMMARIZER_PROMPT),
        ("human", SUMMARIZER_INPUT),
    ])

    chain = prompt | deterministic_llm

    return {
            "summary": chain.invoke({
                "previous_summary": previous_summary,
                "conversation_text": conversation_text
            }).content,
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *remaining_messages
            ]
        }

graph = StateGraph(ChatbotState)

preference_tool_node = ToolNode(tools=TOOLS, messages_key="tool_message")

# Add nodes
graph.add_node("sentiment_node", sentiment_node)
graph.add_node("update_score_node", update_score_node)
graph.add_node("tsundere_chatbot_node", tsundere_chatbot_node)
graph.add_node("extract_user_info_node", extract_user_info_node)
graph.add_node("preference_tool_node", preference_tool_node)
graph.add_node("context_compaction_node", context_compaction_node)

# Define edges (flow)

graph.add_edge(START, "sentiment_node")
graph.add_edge(START, "extract_user_info_node")
graph.add_conditional_edges("extract_user_info_node", tools_router,
                            {"call_tool": "preference_tool_node",
                             END: END})
graph.add_edge("preference_tool_node", END)
graph.add_conditional_edges("sentiment_node", should_update_score,
    {
        "update":"update_score_node",
        "skip":"tsundere_chatbot_node"
    }     
)
graph.add_edge("update_score_node", "tsundere_chatbot_node")
graph.add_conditional_edges("tsundere_chatbot_node", context_compaction_router,
    {
        "compact":"context_compaction_node",
        "skip":END
    }     
)
graph.add_edge("context_compaction_node", END)
# graph.add_edge("tsundere_chatbot_node", END)


# Compile
app = graph.compile(checkpointer=redis_checkpoint)

def call_graph(user_input: str, user_id: str, thread_id:str) -> Tuple[str, float]:
    
    config = {"configurable": {
    "thread_id": thread_id
    }}

    result = app.invoke({
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id
            }, config=config)
    
    return result["messages"][-1].content, result.get("current_score", INITIAL_SCORE)

if __name__ == "__main__":
    app.get_graph().draw_mermaid_png(output_file_path='debug.png')
    config = {"configurable": {
    "thread_id": "twotwotwotwo"
    }}
    

    while True: 
        user_input = input("User: ")
        if(user_input in ["exit", "end"]):
            break
        else: 
            result = app.invoke({
                "messages": [HumanMessage(content=user_input)],
                "user_id": "ad3"
            }, config=config)

            print("AI: " + result["messages"][-1].content)