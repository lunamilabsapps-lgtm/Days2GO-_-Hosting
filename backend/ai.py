import os
import re
import json
from emergentintegrations.llm.chat import LlmChat, UserMessage
from core import db, uid, iso, get_settings, notify


class AIError(Exception):
    pass


def ai_configured():
    return bool(os.environ.get("EMERGENT_LLM_KEY"))


async def call_ai(purpose, system, prompt, business_id=None, max_tokens=2500):
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise AIError("AI key (EMERGENT_LLM_KEY) is not configured")
    s = await get_settings()
    model = s["research"]["ai_model"]
    chat = LlmChat(api_key=key, session_id=f"{purpose}-{uid()}", system_message=system) \
        .with_model("anthropic", model).with_params(max_tokens=max_tokens)
    try:
        text = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        await notify("api_failure", "AI request failed", str(e)[:300], "high")
        raise AIError(str(e)[:300])
    in_tok = (len(system) + len(prompt)) // 4
    out_tok = len(text or "") // 4
    cost = in_tok / 1e6 * s["research"]["ai_input_cost_per_mtok"] + out_tok / 1e6 * s["research"]["ai_output_cost_per_mtok"]
    await db.ai_usage.insert_one({"id": uid(), "purpose": purpose, "business_id": business_id, "model": model,
                                  "input_tokens_est": in_tok, "output_tokens_est": out_tok,
                                  "cost_usd_est": round(cost, 5), "created_at": iso()})
    return text or ""


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text or "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("AI did not return JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AIError(f"AI JSON parse error: {e}")
