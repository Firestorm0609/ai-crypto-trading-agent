from openai import OpenAI
from config import MISTRAL_API_KEYS, MISTRAL_MODEL
from all_tools import ALL_TOOLS, TOOL_MAP
from super_tools import SUPER_TOOLS, SUPER_TOOL_MAP
from web_tools import WEB_TOOLS, WEB_TOOL_MAP
from trend_scanner import TREND_TOOLS, TREND_TOOL_MAP
import json

MERGED = {**TOOL_MAP, **SUPER_TOOL_MAP, **WEB_TOOL_MAP, **TREND_TOOL_MAP}
ALL_TOOLS_LIST = ALL_TOOLS + SUPER_TOOLS + WEB_TOOLS + TREND_TOOLS

client = OpenAI(api_key=MISTRAL_API_KEYS[0], base_url='https://api.mistral.ai/v1')

system_prompt = """You are a crypto trading agent with FULL WEB ACCESS.

CRITICAL RULES:
1. When user asks about a token: ALWAYS use scan_token or web_search to find info
2. When user says "check the web": IMMEDIATELY call web_search
3. NEVER say "I can't find it" without searching first
4. NEVER give up - if one tool fails, try another approach
5. Plain text only - no markdown, no **, no #

If you don't know something, SEARCH. Never say "not found"."""

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "whats the name of this token 0xf4eaec43e22251547fbd2cb2f153e041c3aa4ea6"}
]

for step in range(5):
    response = client.chat.completions.create(
        model="mistral-small-latest",
        messages=messages,
        tools=ALL_TOOLS_LIST,
        tool_choice="auto",
        max_tokens=1000
    )
    
    choice = response.choices[0]
    
    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            tool_name = tc.function.name
            tool_args = json.loads(tc.function.arguments)
            print(f"Step {step+1}: {tool_name}({tool_args})")
            
            if tool_name in MERGED:
                result = MERGED[tool_name](tool_args)
                print(f"  Result: {result[:150]}")
                messages.append({"role": "assistant", "content": choice.message.content or "", "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tool_name, "arguments": tc.function.arguments}}]})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:1000]})
            else:
                print(f"  Tool not found: {tool_name}")
    else:
        print(f"Step {step+1}: FINAL - {choice.message.content}")
        break
