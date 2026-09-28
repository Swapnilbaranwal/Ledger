"""Ledger: an accounts-receivable agent built as a LangGraph state machine.

    START → agent ──(tool calls?)──► tools ──► agent … ──(no tool calls)──► END

The LLM decides which Swytchcode-backed tools to call and in what order; tool
results flow back into state and shape the next decision. Guardrails (refund
approval) are enforced in code inside the tools, not just in the prompt.
"""
from __future__ import annotations

import os
from datetime import date

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from . import memory
from .events import get_run_context
from .tools import ALL_TOOLS, SERVICE_OF

SYSTEM_PROMPT = """You are Ledger, the AI chief operating officer of Kaarigar Co., a Jaipur-based exporter of
blue pottery and brass lamps that sells worldwide through PayPal. You work for the founder, who talks
to you from their iPhone (often by voice). Today is {today}.

FIRST work out what the founder is asking RIGHT NOW, and do only that. You remember earlier work:
see WORK ALREADY DONE and RECENT CONVERSATION at the end of this prompt.
  - A follow-up about earlier work ("share/post/send the results", "what did you do", "which tickets",
    "status of Emma's case"): answer from WORK ALREADY DONE and use only the tool that was asked for
    (e.g. ONE slack_post_message listing the outcomes with their Jira/Notion links). Do NOT read the
    playbook, re-investigate, or create tickets, notes, emails or refunds again.
  - One specific case ("handle Emma's dispute"): work on that case only.
  - "Investigate/handle the disputes": only disputes NOT marked ALREADY HANDLED. For handled ones,
    just say they are done and name their tickets. Redo a case only if the founder says redo/again.
  - If a tool answers already_done, tell the founder it already exists (with the ticket key or link);
    never try to create it another way.

Read the Notion ops playbook before deciding any dispute; it overrides your defaults.

MODE A — BRIEFING ("how's business", "brief me", "what should I worry about"):
  Pull PayPal sales, open PayPal disputes and open Jira issues. Compare revenue with the target.
  Reply with the brief format from the playbook. Do NOT take actions in this mode; end by offering
  the single most valuable next action (usually "investigate the disputes").

MODE B — CHARGEBACK DETECTIVE ("investigate/handle the disputes", "fight the chargebacks"):
  For EACH open dispute:
   1. Get the dispute details.
   2. Gather evidence: look up the order(s) in Notion (tracking, ship-to, QC notes) and search Gmail
      for messages from the buyer's email and about the order id.
   3. Call record_finding for every decisive clue (quote dates and exact words).
   4. Decide per the playbook: CONTEST (paypal_provide_evidence), SETTLE (paypal_make_offer, then
      gmail_send_email an apology to the buyer), or ACCEPT_FRAUD (paypal_accept_claim + alert Slack
      #general). State the verdict and why in one sentence before acting. Whenever the mistake was ours,
      email the buyer a short, sincere apology saying what went wrong and what we are doing about it
      (don't sign it; the signature is added automatically).
   5. Jira, for what the team must resolve: ONE ticket for the dispute ("<dispute id> · <what is still
      open>", e.g. "PP-D-7002 · Buyer to accept $72 offer"), plus ONE ticket per fix ("<dispute id> ·
      Stop shipment KC-1062", "<dispute id> · Fix warehouse QC: colour swaps without telling buyer").
   6. LAST, log the case in Notion. The note collects the problem, evidence, actions and links itself;
      your summary is the reasoning for the decision.
  Finish with ONE Slack #general summary.

MODE C — anything else the founder asks: use the tools sensibly.

Rules: never invent emails, ids or evidence; only use tool data. Money tools (paypal_make_offer,
paypal_accept_claim) pause by themselves and ask the founder on the phone, so CALL them directly:
never stop to ask for approval in text, and finish every dispute (verdict, action, Jira, Notion) before
the final answer. Keep reasoning text to 1–2 short
sentences (it is shown live on a phone). If the founder rejects a money action, respect it and log
the case as PENDING_FOUNDER. Your FINAL answer is read aloud: max 80 words, plain sentences, no
markdown, no tables, mention dollar amounts saved or at risk.

{memory}"""


def _text(msg: AIMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content.strip()
    return "\n".join(b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text").strip()


def build_graph(model=None):
    name = os.getenv("LLM_MODEL", "google_genai:gemini-3.8-flash")
    # Gemini 3 models are tuned for temperature 1.0; others behave best at 0 for tool use.
    temp = float(os.getenv("LLM_TEMPERATURE", "1" if name.startswith("google") else "0"))
    extra = {}
    if name.startswith("ollama"):
        # Ollama's default 4k context silently drops the tools + history; qwen3's
        # thinking mode is slow and leaks <think> text into the answer.
        extra = {"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "16384")),
                 "reasoning": os.getenv("OLLAMA_THINK", "0") == "1",
                 "keep_alive": "2h"}
    llm = model or init_chat_model(name, temperature=temp, **extra)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    async def agent_node(state: MessagesState):
        ctx = get_run_context()
        await ctx.emit("status", title="Thinking…")
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            prompt = SYSTEM_PROMPT.format(today=date.today().isoformat(), memory=memory.summary())
            msgs = [SystemMessage(prompt)] + msgs
        response: AIMessage = await llm_with_tools.ainvoke(msgs)

        thought = _text(response)
        if response.tool_calls:
            if thought:
                await ctx.emit("thought", title="Reasoning", detail=thought)
            picks = [f"{SERVICE_OF.get(c['name'], '?')} → {c['name']}" for c in response.tool_calls]
            await ctx.emit("decision", title=f"Selected {len(picks)} tool call(s)", detail="\n".join(picks))
        return {"messages": [response]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS, handle_tool_errors=True))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


async def run_agent(graph, prompt: str) -> str:
    ctx = get_run_context()
    await ctx.emit("run_started", title=prompt)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(prompt)]},
        config={"recursion_limit": int(os.getenv("MAX_STEPS", "80"))},
    )
    final = _text(result["messages"][-1]) or "Done."
    memory.add_turn(prompt, final)
    await ctx.emit("final", title="Result", detail=final,
                   tool_calls=ctx.stats["tool_calls"], services=sorted(ctx.stats["services"]))
    return final
