from langchain_openai import ChatOpenAI
from langchain_qwq import ChatQwen
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, Tuple
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, BaseMessage, RemoveMessage, SystemMessage, AIMessage
from langgraph.prebuilt import ToolNode

from sentiment import SentimentResult, SENTIMENT_PROMPT
from persona import TSUNDERE_BASE_PROMPT, PERSONA_MODES, TSUNDERE_IMPROVE_FEEDBACK_PROMPT, JAILBREAK_TSUNDERE_PROMPT, get_emotional_mode
from preference import TOOLS, TOOL_PROMPT
from redis_manager import redis_memory
from context_summarizer import format_message, SUMMARIZER_PROMPT, SUMMARIZER_INPUT
from reflection import ReflectionResult, REFLECTION_PROMPT, REFLECTION_INPUT
from input_guardrail import GuardrailResult, GUARDRAIL_PROMPT

from pprint import pprint

from langgraph.checkpoint.redis import RedisSaver

redis_cm = RedisSaver.from_conn_string("redis://redis:6379")
redis_checkpoint = redis_cm.__enter__()
redis_checkpoint.setup()

INITIAL_SCORE = 0.0
INITIAL_STREAK = 0
MAX_HISTORY = 20 # Because 10 HumanMessage + 10 AIMessage = 20 Messages
MAX_REFLECTION_ROUNDS = 2
class ChatbotState(TypedDict):
    """State for flow through the entire graph"""
    user_name: str
    user_id: str
    sentiment_analysis: SentimentResult
    guardrail_result: GuardrailResult
    streak: int
    current_score: float
    persona_mode: str
    messages: Annotated[list[BaseMessage], add_messages]
    
    tool_message: list
    
    summary: str

    draft_message: BaseMessage
    revise_needed: bool
    reflection_feedback: str
    reflection_count: int

llm = ChatOpenAI(model = "typhoon-v2.5-30b-a3b-instruct", base_url="https://api.opentyphoon.ai/v1", max_tokens= 8192)
deterministic_llm = ChatOpenAI(model = "typhoon-v2.5-30b-a3b-instruct", base_url="https://api.opentyphoon.ai/v1", max_tokens= 8192, temperature=0)
tool_calling_llm = ChatQwen(model="qwen3.5-flash")

def guardrail_node(state: ChatbotState) -> ChatbotState:
    
    structured_llm = deterministic_llm.with_structured_output(GuardrailResult)

    prompt = ChatPromptTemplate.from_messages([
        ("system", GUARDRAIL_PROMPT),
        ("human", "{message}"),
    ])

    chain = prompt | structured_llm

    return {
        "guardrail_result": chain.invoke({"message": state["messages"][-1].content})
    }

def guardrail_score_node(state: ChatbotState) -> ChatbotState:
    current_score = state.get("current_score", INITIAL_SCORE)
    streak = state.get("streak", INITIAL_STREAK)

    if streak < 0:
        current_score -= (1 + (abs(streak) * 10/100))
    else:
        current_score -= 1
    
    current_score = max(min(current_score, 10), -10)

    streak = streak - 1 if streak <= 0 else 0

    return {
        "current_score": current_score,
        "streak": streak
    }

def guardrail_router(state: ChatbotState):
    if state["guardrail_result"].block_type in ["jailbreak", "dangerous"]:
        return "blocked"
    return "allowed"

def jailbreak_response_node(state: ChatbotState) -> ChatbotState:
    prompt = ChatPromptTemplate.from_messages([
        ("system", JAILBREAK_TSUNDERE_PROMPT),
        ("human", "{message}"),
    ])
    chain = prompt | llm

    user_name = state.get("user_name")
    if user_name is None:
        try:
            user_name = redis_memory.load_user_name(state["user_id"])
        except Exception:
            user_name = None

    current_score = state.get("current_score", INITIAL_SCORE)
    mode = get_emotional_mode(current_score)
    result = chain.invoke({
        "user_name": user_name if user_name is not None else "ไม่มี",
        "mode": PERSONA_MODES[mode],
        "block_type": state["guardrail_result"].block_type,
        "reason": state["guardrail_result"].reason,
        "message": state["messages"][-1].content,
    })

    return {
        "user_name": user_name,
        "messages": [result]
    }

def allowed_entry_node(state: ChatbotState) -> ChatbotState:
    return {}

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
    # if state["guardrail_result"].block_type in ["jailbreak", "dangerous"]:
    #     return "block"
    if state["sentiment_analysis"].sentiment in ["positive","negative"]:
        return "update"
    return "skip"

def update_score_node(state: ChatbotState) -> ChatbotState:
    current_score = state.get("current_score", INITIAL_SCORE)
    streak = state.get("streak", INITIAL_STREAK)
    
    sentiment = state["sentiment_analysis"].sentiment
    intensity = state["sentiment_analysis"].intensity

    score_update_sign = 1 if sentiment == "positive" else -1


    if (streak > 0 and sentiment == "positive") or (streak < 0 and sentiment == "negative"):
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
    if not user_name:
        try:
            user_name = redis_memory.load_user_name(state["user_id"])
        except:
            user_name = None

    return {
        "tool_message": [chain.invoke({
            "user_name": user_name if user_name else "None",
            "user_preference": user_preference,
            "message": state["messages"][-1].content,
            })]
    }

def tools_router(state: ChatbotState):
    last_message = state["tool_message"][-1]

    if(hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0):
        return "call_tool"
    else: 
        return END
    
preference_tool_node = ToolNode(tools=TOOLS, messages_key="tool_message")   

def tsundere_chatbot_node(state: ChatbotState) -> ChatbotState:

    current_score = state.get("current_score", INITIAL_SCORE)
    
    reflection_feedback = state.get("reflection_feedback", "")
    previous_draft = state.get("draft_message", "")
        
    mode = get_emotional_mode(current_score)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", TSUNDERE_BASE_PROMPT),
        MessagesPlaceholder("message"),
    ])

    user_name = state.get("user_name")
    if not user_name:
        try:
            user_name = redis_memory.load_user_name(state["user_id"])
        except:
            user_name = None

    model_messages = list(state["messages"])

    summary = state.get("summary")
    if summary:
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

    if previous_draft and reflection_feedback:
        prompt = ChatPromptTemplate.from_messages([
        ("system", TSUNDERE_IMPROVE_FEEDBACK_PROMPT),
            MessagesPlaceholder("message"),
        ])
        chain = prompt | llm

        return {
        "user_name": user_name,
        "draft_message": chain.invoke({
            "user_name": user_name if user_name is not None else "(ไม่มี)",
            "mode": PERSONA_MODES[mode],
            "reflection_feedback": reflection_feedback,
            "draft_message": previous_draft.content,
            "message": model_messages})
        }

    chain = prompt | llm
    return {
        "user_name": user_name,
        "draft_message": chain.invoke({
            "user_name": user_name if user_name is not None else "(ไม่มี)",
            "mode": PERSONA_MODES[mode],
            "message": model_messages,
            "interpersonal_sentiment": state["sentiment_analysis"].sentiment,
            "sentiment_intensity": state["sentiment_analysis"].intensity
            })
    }

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
            "summary": chain.invoke({ # Add summary text
                "previous_summary": previous_summary,
                "conversation_text": conversation_text
            }).content,
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES), # Removing Old Message
                *remaining_messages
            ]
        }

def reflective_node(state: ChatbotState) -> ChatbotState:
    reflection_count = state.get("reflection_count", 0)
    
    # กัน loop
    if reflection_count >= MAX_REFLECTION_ROUNDS:
        return {
            "revise_needed": False,
            "reflection_feedback": "",
            "reflection_count": reflection_count
        }

    last_user_message = ""
    last_ai_message = ""
    for msg in reversed(state["messages"]):
        if last_user_message and last_ai_message:
            break
        if not last_user_message and msg.type == "human":
            last_user_message = msg.content
        if not last_ai_message and msg.type == "ai":
            last_ai_message = msg.content

    draft_message = state.get("draft_message").content

    current_score = state.get("current_score", INITIAL_SCORE)

    mode = get_emotional_mode(current_score)

    structured_llm = deterministic_llm.with_structured_output(ReflectionResult)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", REFLECTION_PROMPT),
        ("human", REFLECTION_INPUT),
    ])

    chain = prompt | structured_llm

    result = chain.invoke({ # Add summary text
                "last_user_message": last_user_message,
                "draft_message": draft_message,
                "last_ai_message": last_ai_message,
                "mode": PERSONA_MODES[mode],
                "interpersonal_sentiment": state["sentiment_analysis"].sentiment,
                "sentiment_intensity": state["sentiment_analysis"].intensity
            })

    return {
        "revise_needed": result.revise_needed,
        "reflection_feedback": result.feedback,
        "reflection_count": reflection_count + 1,
    }

def commit_draft_message_node(state: ChatbotState) -> ChatbotState:
    draft_response = state.get("draft_message", "")

    if not draft_response:
        return {}

    return {
        "messages": [draft_response],
        "draft_message": "",
        "reflection_feedback": "",
        "revise_needed": False,
        "reflection_count": 0,
    }

def reflective_router(state: ChatbotState):
    if state.get("revise_needed", False):
        return "retry"
    return "pass"

graph = StateGraph(ChatbotState)

# Add nodes
graph.add_node("guardrail_node", guardrail_node)
graph.add_node("guardrail_score_node", guardrail_score_node)
graph.add_node("allowed_entry_node", allowed_entry_node)
graph.add_node("jailbreak_response_node", jailbreak_response_node)
graph.add_node("sentiment_node", sentiment_node)
graph.add_node("update_score_node", update_score_node)
graph.add_node("tsundere_chatbot_node", tsundere_chatbot_node)
graph.add_node("extract_user_info_node", extract_user_info_node)
graph.add_node("preference_tool_node", preference_tool_node)
graph.add_node("context_compaction_node", context_compaction_node)
graph.add_node("reflective_node", reflective_node)
graph.add_node("commit_draft_message_node", commit_draft_message_node)

# Define edges (flow)

graph.add_edge(START, "guardrail_node")
graph.add_conditional_edges("guardrail_node", guardrail_router,
    {
        "blocked": "guardrail_score_node",
        "allowed": "allowed_entry_node"
    }
)
graph.add_edge("guardrail_score_node", "jailbreak_response_node")
graph.add_conditional_edges("jailbreak_response_node", context_compaction_router,
    {
        "compact":"context_compaction_node",
        "skip":END
    }     
)
graph.add_edge("jailbreak_response_node", END)

graph.add_edge("allowed_entry_node", "sentiment_node")
graph.add_edge("allowed_entry_node", "extract_user_info_node")
graph.add_conditional_edges("extract_user_info_node", tools_router,
    {
        "call_tool": "preference_tool_node",
        END: END
    }
)
graph.add_edge("preference_tool_node", END)
graph.add_conditional_edges("sentiment_node", should_update_score,
    {
        "update":"update_score_node",
        "skip":"tsundere_chatbot_node"
    }     
)
graph.add_edge("update_score_node", "tsundere_chatbot_node")
graph.add_edge("tsundere_chatbot_node", "reflective_node")
graph.add_conditional_edges("reflective_node", reflective_router,
    {
        "retry":"tsundere_chatbot_node",
        "pass":"commit_draft_message_node"
    }     
)
graph.add_conditional_edges("commit_draft_message_node", context_compaction_router,
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
    "thread_id": "sevenseven2"
    }}
    

    while True: 
        user_input = input("User: ")
        if(user_input in ["exit", "end"]):
            break
        else: 
            result = app.invoke({
                "messages": [HumanMessage(content=user_input)],
                "user_id": "ad4"
            }, config=config)

            print("AI: " + result["messages"][-1].content)