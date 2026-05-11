"""
Agentic chat system with provider switching.

Supports two backends, selected via the CHAT_PROVIDER environment variable:
  - "openai"    (default) — LangGraph ReAct agent using OpenAI GPT models
  - "anthropic"           — Anthropic native tool-use API with streaming

Set CHAT_PROVIDER=anthropic in your .env to switch to Anthropic (requires ANTHROPIC_API_KEY).
"""

import os
import uuid
import asyncio
import contextvars
import traceback
from typing import List, Optional, AsyncGenerator, Any, Tuple

from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

# Context variable to store config for tools
agent_config_context: contextvars.ContextVar[dict] = contextvars.ContextVar('agent_config', default=None)

from models.app import App
from models.chat import Message, ChatSession, PageContext
from models.conversation import Conversation
from utils.retrieval.tools import (
    get_conversations_tool,
    search_conversations_tool,
    get_memories_tool,
    search_memories_tool,
    get_action_items_tool,
    create_action_item_tool,
    update_action_item_tool,
    get_omi_product_info_tool,
    perplexity_web_search_tool,
    get_calendar_events_tool,
    create_calendar_event_tool,
    update_calendar_event_tool,
    delete_calendar_event_tool,
    get_gmail_messages_tool,
    get_apple_health_steps_tool,
    get_apple_health_sleep_tool,
    get_apple_health_heart_rate_tool,
    get_apple_health_workouts_tool,
    get_apple_health_summary_tool,
    search_files_tool,
    manage_daily_summary_tool,
    create_chart_tool,
    get_screen_activity_tool,
    search_screen_activity_tool,
    save_user_preference_tool,
)
from utils.retrieval.tools.app_tools import load_app_tools, get_tool_status_message
from utils.retrieval.safety import AgentSafetyGuard, SafetyGuardError
from utils.llm.clients import llm_agent, llm_agent_stream, anthropic_client, ANTHROPIC_AGENT_MODEL
from utils.llm.chat import _get_agentic_qa_prompt
from utils.observability.langsmith import get_chat_tracer_callbacks
from utils.other.endpoints import timeit
import logging

# Import langsmith traceable if available
try:
    from langsmith import traceable as _traceable
except ImportError:
    def _traceable(**kwargs):
        def decorator(func):
            return func
        return decorator


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider switch — change this one env var to flip backends
# ---------------------------------------------------------------------------
# CHAT_PROVIDER=openai    → LangGraph + OpenAI GPT  (default, no Anthropic key needed)
# CHAT_PROVIDER=anthropic → Anthropic Claude native API
CHAT_PROVIDER = os.getenv('CHAT_PROVIDER', 'openai').lower()
logger.info(f"Chat provider: {CHAT_PROVIDER}")

# ---------------------------------------------------------------------------
# Shared tool list — used by both providers
# ---------------------------------------------------------------------------
# IMPORTANT: Keep this list fixed and in this exact order.
# Both OpenAI and Anthropic cache the tool definitions as part of the request
# prefix — changing the order breaks the cache and costs more tokens.
# Dynamic per-user app tools are appended AFTER this list.
CORE_TOOLS = [
    get_conversations_tool,
    search_conversations_tool,
    get_memories_tool,
    search_memories_tool,
    get_action_items_tool,
    create_action_item_tool,
    update_action_item_tool,
    get_omi_product_info_tool,
    perplexity_web_search_tool,
    get_calendar_events_tool,
    create_calendar_event_tool,
    update_calendar_event_tool,
    delete_calendar_event_tool,
    get_gmail_messages_tool,
    get_apple_health_steps_tool,
    get_apple_health_sleep_tool,
    get_apple_health_heart_rate_tool,
    get_apple_health_workouts_tool,
    get_apple_health_summary_tool,
    search_files_tool,
    manage_daily_summary_tool,
    create_chart_tool,
    get_screen_activity_tool,
    search_screen_activity_tool,
    save_user_preference_tool,
]

# Standard tool names (used to detect app tools by exclusion)
STANDARD_TOOL_NAMES = {t.name for t in CORE_TOOLS}


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def get_tool_display_name(tool_name: str, tool_obj: Optional[Any] = None) -> str:
    """Convert tool name to user-friendly display name."""
    status_msg = get_tool_status_message(tool_name)
    if status_msg:
        return status_msg

    if tool_obj and hasattr(tool_obj, 'status_message') and tool_obj.status_message:
        return tool_obj.status_message

    tool_display_map = {
        'get_calendar_events_tool': 'Checking calendar',
        'create_calendar_event_tool': 'Creating calendar event',
        'update_calendar_event_tool': 'Updating calendar event',
        'delete_calendar_event_tool': 'Deleting calendar event',
        'get_gmail_messages_tool': 'Checking Gmail',
        'perplexity_web_search_tool': 'Searching the web',
        'get_conversations_tool': 'Searching conversations',
        'search_conversations_tool': 'Searching conversations',
        'get_memories_tool': 'Searching memories',
        'search_memories_tool': 'Searching memories',
        'get_action_items_tool': 'Checking action items',
        'create_action_item_tool': 'Creating action item',
        'update_action_item_tool': 'Updating action item',
        'get_omi_product_info_tool': 'Looking up product info',
        'manage_daily_summary_tool': 'Updating notification settings',
        'create_chart_tool': 'Creating chart',
        'get_screen_activity_tool': 'Checking screen activity',
        'search_screen_activity_tool': 'Searching screen activity',
        'save_user_preference_tool': 'Saving preference',
    }

    if tool_name in tool_display_map:
        return tool_display_map[tool_name]

    if 'calendar' in tool_name.lower():
        return 'Checking calendar'
    elif 'perplexity' in tool_name.lower() or 'search' in tool_name.lower():
        return 'Searching the web'
    elif 'memory' in tool_name.lower():
        return 'Searching memories'
    elif 'conversation' in tool_name.lower():
        return 'Searching conversations'
    elif 'action' in tool_name.lower():
        return 'Checking action items'

    return tool_name.replace('_', ' ').title()


def _extract_app_id(tool_name: str) -> Optional[str]:
    """Extract app_id from an app tool name (format: appid_toolname)."""
    if tool_name not in STANDARD_TOOL_NAMES and '_' in tool_name:
        parts = tool_name.split('_', 1)
        if len(parts) == 2:
            return parts[0]
    return None


async def _emit_calendar_status(callback, tool_name: str, output: str):
    """Emit calendar-specific completion status messages."""
    if 'calendar' not in tool_name.lower():
        return

    if 'create' in tool_name.lower():
        if output and ('Successfully created' in output or '✅' in output):
            await callback.put_thought('Event created successfully')
        elif output and ('Error' in output or 'error' in output.lower()):
            await callback.put_thought('Failed to create event')
        else:
            await callback.put_thought('Creating event...')
    elif 'update' in tool_name.lower():
        if output and ('Successfully updated' in output or '✅' in output):
            await callback.put_thought('Event updated successfully')
        elif output and ('Error' in output or 'error' in output.lower()):
            await callback.put_thought('Failed to update event')
        else:
            await callback.put_thought('Updating event...')
    elif 'delete' in tool_name.lower():
        if output and ('Successfully deleted' in output or '✅' in output):
            await callback.put_thought('Event deleted successfully')
        elif output and ('Error' in output or 'error' in output.lower()):
            await callback.put_thought('Failed to delete event')
        else:
            await callback.put_thought('Deleting event...')
    elif 'get' in tool_name.lower() or 'search' in tool_name.lower():
        if output and len(output) > 0:
            await callback.put_thought('Found calendar events')
        else:
            await callback.put_thought('No events found')


# ---------------------------------------------------------------------------
# Streaming callback — base class (plain queue, used by Anthropic path)
# ---------------------------------------------------------------------------

class AsyncStreamingCallback:
    """Queue-based callback for streaming responses with data/think prefixes."""

    def __init__(self):
        self.queue = asyncio.Queue()

    async def put_data(self, text):
        await self.queue.put(f"data: {text}")

    async def put_thought(self, text, app_id: Optional[str] = None):
        if app_id:
            await self.queue.put(f"think: {text}|app_id:{app_id}")
        else:
            await self.queue.put(f"think: {text}")

    def put_thought_nowait(self, text, app_id: Optional[str] = None):
        if app_id:
            self.queue.put_nowait(f"think: {text}|app_id:{app_id}")
        else:
            self.queue.put_nowait(f"think: {text}")

    def put_data_nowait(self, text):
        self.queue.put_nowait(f"data: {text}")

    async def end(self):
        await self.queue.put(None)

    def end_nowait(self):
        self.queue.put_nowait(None)


# ---------------------------------------------------------------------------
# OpenAI streaming callback — extends base with LangChain hooks
# ---------------------------------------------------------------------------

class _OpenAIStreamingCallback(BaseCallbackHandler, AsyncStreamingCallback):
    """LangChain callback handler that feeds tokens into the async queue."""

    def __init__(self):
        BaseCallbackHandler.__init__(self)
        AsyncStreamingCallback.__init__(self)

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        await self.put_data(token)

    async def on_llm_end(self, response, **kwargs) -> None:
        await self.end()

    async def on_llm_error(self, error: Exception, **kwargs) -> None:
        logger.error(f"LLM error: {error}")
        await self.end()


# ---------------------------------------------------------------------------
# OpenAI / LangGraph implementation
# ---------------------------------------------------------------------------

def _messages_to_langchain(messages: List[Message]) -> List:
    """Convert chat messages to LangChain format."""
    result = []
    for msg in messages:
        if msg.sender == 'ai':
            result.append(AIMessage(content=msg.text))
        else:
            result.append(HumanMessage(content=msg.text))
    return result


@timeit
def execute_agentic_chat(
    uid: str,
    messages: List[Message],
    app: Optional[App] = None,
) -> Tuple[str, bool, List[Conversation]]:
    """Execute a non-streaming agentic chat (OpenAI path only)."""
    system_prompt = _get_agentic_qa_prompt(uid, app)

    prompt_name, prompt_commit, prompt_source = None, None, None
    try:
        from utils.observability.langsmith_prompts import get_prompt_metadata
        prompt_name, prompt_commit, prompt_source = get_prompt_metadata()
    except Exception as e:
        logger.error(f"Could not get prompt metadata: {e}")

    tools = list(CORE_TOOLS)
    try:
        app_tools = load_app_tools(uid)
        tools.extend(app_tools)
        if app_tools:
            logger.info(f"Added {len(app_tools)} app tools to chat")
    except Exception as e:
        logger.error(f"Error loading app tools: {e}")

    lc_messages = [SystemMessage(content=system_prompt)]
    lc_messages.extend(_messages_to_langchain(messages))

    agent = create_react_agent(model=llm_agent, tools=tools)

    tracer_callbacks = get_chat_tracer_callbacks(
        run_name="chat.agentic",
        tags=["chat", "agentic"],
        metadata={
            "uid": uid,
            "app_id": app.id if app else None,
            "app_name": app.name if app else None,
            "prompt_name": prompt_name,
            "prompt_commit": prompt_commit,
            "prompt_source": prompt_source,
        },
    )

    config = {
        "configurable": {"user_id": uid, "thread_id": str(uuid.uuid4())},
        "callbacks": tracer_callbacks,
        "run_name": "chat.agentic",
        "tags": ["chat", "agentic"],
        "metadata": {
            "uid": uid,
            "app_id": app.id if app else None,
            "app_name": app.name if app else None,
            "prompt_name": prompt_name,
            "prompt_commit": prompt_commit,
            "prompt_source": prompt_source,
        },
    }

    agent_config_context.set(config)
    result = agent.invoke({"messages": lc_messages}, config=config)

    answer = result["messages"][-1].content if result.get("messages") else "I'm sorry, I couldn't generate a response."
    ask_for_nps = len(result.get("messages", [])) > len(lc_messages) + 1
    return answer, ask_for_nps, []


async def _run_openai_agent_stream(
    agent,
    messages: List,
    config: dict,
    callback: _OpenAIStreamingCallback,
    full_response: List[str],
):
    """Run the LangGraph ReAct agent and feed events into the callback queue."""
    safety_guard = config['configurable'].get('safety_guard')

    try:
        async for event in agent.astream_events({"messages": messages}, config=config, version="v2"):
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    full_response.append(token)
                    await callback.put_data(token)

            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                logger.info(f"Tool started: {tool_name}")

                app_id = _extract_app_id(tool_name)
                tools_list = config.get('configurable', {}).get('tools', [])
                tool_obj = next((t for t in tools_list if hasattr(t, 'name') and t.name == tool_name), None)
                await callback.put_thought(get_tool_display_name(tool_name, tool_obj), app_id=app_id)

                if safety_guard:
                    try:
                        safety_guard.validate_tool_call(tool_name, tool_input)
                        warning = safety_guard.should_warn_user()
                        if warning:
                            await callback.put_thought(warning)
                    except SafetyGuardError as e:
                        await callback.put_data(f"\n\n{str(e)}")
                        logger.error(f"Safety Guard blocked tool call: {e}")
                        await callback.end()
                        return

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output_raw = event.get("data", {}).get("output", "")
                if hasattr(output_raw, 'content'):
                    output = str(output_raw.content)
                elif isinstance(output_raw, str):
                    output = output_raw
                else:
                    output = str(output_raw)

                logger.info(f"Tool ended: {tool_name}")
                await _emit_calendar_status(callback, tool_name, output)

                if safety_guard and output:
                    try:
                        safety_guard.check_context_size(output)
                    except SafetyGuardError as e:
                        await callback.put_data(f"\n\n{str(e)}")
                        logger.error(f"Safety Guard blocked due to context size: {e}")
                        await callback.end()
                        return

            elif kind == "on_tool_error":
                logger.error(f"Tool error: {event.get('name', 'unknown')} — {event.get('data', {}).get('error', '')}")

            elif kind == "on_chain_error":
                logger.error(f"Chain error: {event.get('data', {}).get('error', '')}")

        if safety_guard:
            logger.info(f"Safety Guard final stats: {safety_guard.get_stats()}")

        await callback.end()

    except SafetyGuardError as e:
        await callback.put_data(f"\n\n{str(e)}")
        logger.error(f"Safety Guard stopped execution: {e}")
        await callback.end()
    except Exception as e:
        logger.error(f"Error in _run_openai_agent_stream: {e}")
        traceback.print_exc()
        await callback.end()


async def _execute_agentic_chat_stream_openai(
    uid: str,
    messages: List[Message],
    app: Optional[App],
    callback_data: dict,
    chat_session: Optional[ChatSession],
    context: Optional[PageContext],
) -> AsyncGenerator[str, None]:
    """OpenAI/LangGraph streaming implementation."""
    system_prompt = _get_agentic_qa_prompt(uid, app, messages, context=context)

    prompt_name, prompt_commit, prompt_source = None, None, None
    try:
        from utils.observability.langsmith_prompts import get_prompt_metadata
        prompt_name, prompt_commit, prompt_source = get_prompt_metadata()
    except Exception as e:
        logger.error(f"Could not get prompt metadata: {e}")

    tools = list(CORE_TOOLS)
    try:
        app_tools = load_app_tools(uid)
        tools.extend(app_tools)
        if app_tools:
            logger.info(f"Added {len(app_tools)} app tools to chat")
    except Exception as e:
        logger.error(f"Error loading app tools: {e}")

    lc_messages = [SystemMessage(content=system_prompt)]
    lc_messages.extend(_messages_to_langchain(messages))

    callback = _OpenAIStreamingCallback()
    agent = create_react_agent(model=llm_agent_stream, tools=tools)

    conversations_collected = []
    safety_guard = AgentSafetyGuard(max_tool_calls=25, max_context_tokens=500000)
    langsmith_run_id = str(uuid.uuid4())

    tracer_callbacks = get_chat_tracer_callbacks(
        run_id=langsmith_run_id,
        run_name="chat.agentic.stream",
        tags=["chat", "agentic", "streaming"],
        metadata={
            "uid": uid,
            "app_id": app.id if app else None,
            "app_name": app.name if app else None,
            "chat_session_id": chat_session.id if chat_session else None,
            "has_context": context is not None,
            "context_type": context.type if context else None,
            "num_tools": len(tools),
            "prompt_name": prompt_name,
            "prompt_commit": prompt_commit,
            "prompt_source": prompt_source,
            "provider": "openai",
        },
    )

    config = {
        "run_id": langsmith_run_id,
        "configurable": {
            "user_id": uid,
            "thread_id": str(uuid.uuid4()),
            "conversations_collected": conversations_collected,
            "safety_guard": safety_guard,
            "chat_session_id": chat_session.id if chat_session else None,
            "tools": tools,
        },
        "callbacks": tracer_callbacks,
        "run_name": "chat.agentic.stream",
        "tags": ["chat", "agentic", "streaming"],
        "metadata": {
            "uid": uid,
            "app_id": app.id if app else None,
            "app_name": app.name if app else None,
            "chat_session_id": chat_session.id if chat_session else None,
            "has_context": context is not None,
            "context_type": context.type if context else None,
            "num_tools": len(tools),
            "prompt_name": prompt_name,
            "prompt_commit": prompt_commit,
            "prompt_source": prompt_source,
            "provider": "openai",
        },
    }

    agent_config_context.set(config)

    if callback_data is not None:
        callback_data['langsmith_run_id'] = langsmith_run_id
        callback_data['prompt_name'] = prompt_name
        callback_data['prompt_commit'] = prompt_commit

    full_response = []
    tool_usage_count = 0

    task = asyncio.create_task(
        _run_openai_agent_stream(agent, lc_messages, config, callback, full_response)
    )

    try:
        while True:
            chunk = await callback.queue.get()
            if chunk is None:
                break
            if chunk.startswith("think: "):
                tool_usage_count += 1
            yield chunk

        await task

        if callback_data is not None:
            callback_data['answer'] = ''.join(full_response)
            callback_data['memories_found'] = conversations_collected if conversations_collected else []
            callback_data['ask_for_nps'] = tool_usage_count > 0
            chart_data = config.get('configurable', {}).get('chart_data')
            if chart_data:
                callback_data['chart_data'] = chart_data
            logger.info(f"Collected {len(callback_data['memories_found'])} conversations for citation")

    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as e:
        logger.error(f"Error in OpenAI stream: {e}")
        traceback.print_exc()
        if callback_data is not None:
            callback_data['error'] = str(e)

    yield None


# ---------------------------------------------------------------------------
# Anthropic implementation
# ---------------------------------------------------------------------------

def _langchain_tool_to_anthropic(lc_tool, defer_loading: bool = False) -> dict:
    """Convert a LangChain @tool to Anthropic tool schema format."""
    schema = lc_tool.args_schema.schema()
    properties = {k: v for k, v in schema.get('properties', {}).items() if k != 'config'}
    required = [r for r in schema.get('required', []) if r != 'config']

    cleaned_properties = {}
    for k, v in properties.items():
        cleaned_properties[k] = {pk: pv for pk, pv in v.items() if pk != 'title'}

    tool_def = {
        "name": lc_tool.name,
        "description": lc_tool.description,
        "input_schema": {
            "type": "object",
            "properties": cleaned_properties,
            "required": required,
        },
    }
    if defer_loading:
        tool_def["defer_loading"] = True
    return tool_def


TOOL_SEARCH_TOOL = {
    "type": "tool_search_tool_regex_20251119",
    "name": "tool_search_tool_regex",
}


def _convert_tools_anthropic(core_tools: list, app_tools: list = None) -> tuple:
    """Convert tools to Anthropic schema format and build execution registry.

    Core tools are always visible. App tools are deferred (discovered via tool search).
    Returns (tool_schemas, tool_registry).
    """
    schemas = []

    if app_tools:
        schemas.append(TOOL_SEARCH_TOOL)

    for t in core_tools:
        schemas.append(_langchain_tool_to_anthropic(t, defer_loading=False))

    for t in app_tools or []:
        schemas.append(_langchain_tool_to_anthropic(t, defer_loading=True))

    registry = {t.name: t for t in list(core_tools) + list(app_tools or [])}
    return schemas, registry


def _messages_to_anthropic(messages: List[Message]) -> list:
    """Convert chat messages to Anthropic API format."""
    return [
        {"role": "assistant" if msg.sender == "ai" else "user", "content": msg.text}
        for msg in messages
    ]


@_traceable(name="chat.tool_execution", run_type="tool")
async def _execute_tool_anthropic(tool_name: str, tool_input: dict, registry: dict, configurable: dict) -> str:
    """Execute a LangChain tool by name, injecting RunnableConfig."""
    tool_obj = registry[tool_name]
    config = RunnableConfig(configurable=configurable)
    result = await tool_obj.ainvoke(tool_input, config=config)
    return str(result)


async def _run_anthropic_agent_stream(
    system_prompt: str,
    messages: list,
    tool_schemas: list,
    tool_registry: dict,
    callback: AsyncStreamingCallback,
    full_response: list,
    safety_guard: AgentSafetyGuard,
    configurable: dict,
):
    """Run the Anthropic tool-use loop with streaming.

    Calls Anthropic's messages API, executes tool calls, feeds results back,
    and repeats until the model stops requesting tools.
    """
    system_blocks = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    loop_iteration = 0

    while True:
        loop_iteration += 1
        first_text_in_iteration = True

        try:
            async with anthropic_client.messages.stream(
                model=ANTHROPIC_AGENT_MODEL,
                system=system_blocks,
                messages=messages,
                tools=tool_schemas,
                max_tokens=8192,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, 'type'):
                        if event.delta.type == "text_delta":
                            if first_text_in_iteration and loop_iteration > 1 and full_response:
                                last_char = full_response[-1][-1] if full_response[-1] else ''
                                first_char = event.delta.text[0] if event.delta.text else ''
                                if last_char and first_char and last_char not in (' ', '\n') and first_char not in (' ', '\n'):
                                    full_response.append('\n\n')
                                    await callback.put_data('\n\n')
                            first_text_in_iteration = False
                            full_response.append(event.delta.text)
                            await callback.put_data(event.delta.text)

                    elif event.type == "content_block_start":
                        if hasattr(event.content_block, 'type') and event.content_block.type == "tool_use":
                            tool_name = event.content_block.name
                            if 'tool_search' in tool_name:
                                logger.info(f"Tool search invoked (server-side)")
                                continue
                            app_id = _extract_app_id(tool_name)
                            tool_obj = tool_registry.get(tool_name)
                            await callback.put_thought(get_tool_display_name(tool_name, tool_obj), app_id=app_id)
                            logger.info(f"Tool started: {tool_name}")

                response = await stream.get_final_message()

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            await callback.put_data(f"\n\nSorry, I encountered an error. Please try again.")
            await callback.end()
            return

        if response.stop_reason != "tool_use":
            break

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_results = []

        for block in tool_use_blocks:
            try:
                safety_guard.validate_tool_call(block.name, block.input)
                warning = safety_guard.should_warn_user()
                if warning:
                    await callback.put_thought(warning)
            except SafetyGuardError as e:
                await callback.put_data(f"\n\n{str(e)}")
                logger.error(f"Safety Guard blocked tool call: {e}")
                await callback.end()
                return

            try:
                result = await _execute_tool_anthropic(block.name, block.input, tool_registry, configurable)
            except Exception as e:
                logger.error(f"Tool execution error ({block.name}): {e}")
                result = f"Error executing tool: {str(e)}"

            logger.info(f"Tool ended: {block.name}")
            await _emit_calendar_status(callback, block.name, result)

            try:
                safety_guard.check_context_size(result)
            except SafetyGuardError as e:
                await callback.put_data(f"\n\n{str(e)}")
                logger.error(f"Safety Guard blocked due to context size: {e}")
                await callback.end()
                return

            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

    logger.info(f"Safety Guard final stats: {safety_guard.get_stats()}")
    await callback.end()


@_traceable(name="chat.anthropic.stream", run_type="chain")
async def _execute_agentic_chat_stream_anthropic(
    uid: str,
    messages: List[Message],
    app: Optional[App],
    callback_data: dict,
    chat_session: Optional[ChatSession],
    context: Optional[PageContext],
) -> AsyncGenerator[str, None]:
    """Anthropic streaming implementation."""
    system_prompt = _get_agentic_qa_prompt(uid, app, messages, context=context)

    prompt_name, prompt_commit, prompt_source = None, None, None
    try:
        from utils.observability.langsmith_prompts import get_prompt_metadata
        prompt_name, prompt_commit, prompt_source = get_prompt_metadata()
    except Exception as e:
        logger.error(f"Could not get prompt metadata: {e}")

    core_tools = list(CORE_TOOLS)
    app_tools = []
    try:
        app_tools = load_app_tools(uid)
        if app_tools:
            logger.info(f"Loaded {len(app_tools)} app tools (deferred via tool search)")
    except Exception as e:
        logger.error(f"Error loading app tools: {e}")

    tool_schemas, tool_registry = _convert_tools_anthropic(core_tools, app_tools)
    anthropic_messages = _messages_to_anthropic(messages)
    callback = AsyncStreamingCallback()
    conversations_collected = []
    safety_guard = AgentSafetyGuard(max_tool_calls=25, max_context_tokens=500000)
    langsmith_run_id = str(uuid.uuid4())

    configurable = {
        "user_id": uid,
        "thread_id": str(uuid.uuid4()),
        "conversations_collected": conversations_collected,
        "safety_guard": safety_guard,
        "chat_session_id": chat_session.id if chat_session else None,
        "tools": core_tools + app_tools,
    }

    agent_config_context.set({"configurable": configurable})

    if callback_data is not None:
        callback_data['langsmith_run_id'] = langsmith_run_id
        callback_data['prompt_name'] = prompt_name
        callback_data['prompt_commit'] = prompt_commit

    full_response = []
    tool_usage_count = 0

    task = asyncio.create_task(
        _run_anthropic_agent_stream(
            system_prompt,
            anthropic_messages,
            tool_schemas,
            tool_registry,
            callback,
            full_response,
            safety_guard,
            configurable,
        )
    )

    try:
        while True:
            chunk = await callback.queue.get()
            if chunk is None:
                break
            if chunk.startswith("think: "):
                tool_usage_count += 1
            yield chunk

        await task

        if callback_data is not None:
            callback_data['answer'] = ''.join(full_response)
            callback_data['memories_found'] = conversations_collected if conversations_collected else []
            callback_data['ask_for_nps'] = tool_usage_count > 0
            chart_data = configurable.get('chart_data')
            if chart_data:
                callback_data['chart_data'] = chart_data
            logger.info(f"Collected {len(callback_data['memories_found'])} conversations for citation")

    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as e:
        logger.error(f"Error in Anthropic stream: {e}")
        traceback.print_exc()
        if callback_data is not None:
            callback_data['error'] = str(e)

    yield None


# ---------------------------------------------------------------------------
# Public API — routes to the selected provider
# ---------------------------------------------------------------------------

async def execute_agentic_chat_stream(
    uid: str,
    messages: List[Message],
    app: Optional[App] = None,
    callback_data: dict = None,
    chat_session: Optional[ChatSession] = None,
    context: Optional[PageContext] = None,
) -> AsyncGenerator[str, None]:
    """Execute an agentic chat interaction with streaming.

    Provider is selected by the CHAT_PROVIDER env var (default: openai).
    Yields formatted chunks with "data: " or "think: " prefixes.
    """
    if CHAT_PROVIDER == 'anthropic':
        async for chunk in _execute_agentic_chat_stream_anthropic(
            uid, messages, app, callback_data, chat_session, context
        ):
            yield chunk
    else:
        async for chunk in _execute_agentic_chat_stream_openai(
            uid, messages, app, callback_data, chat_session, context
        ):
            yield chunk
