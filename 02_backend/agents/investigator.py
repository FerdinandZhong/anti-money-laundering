import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "02_backend"))

import json
import re
from typing import Generator
from uuid import uuid4

from agents.llm_client import chat
from agents.tools import TOOLS

MAX_ITERATIONS = 8

_TOOL_LIST = "\n".join(f"- {name}" for name in TOOLS)

SYSTEM_PROMPT = f"""You are an AML investigator agent. You have access to the following tools:
{_TOOL_LIST}

To use a tool, output: <tool_call>tool_name({{"arg": "value"}})</tool_call>
When you have gathered enough evidence, output your final report wrapped in <final_report>...</final_report>.

Your report must include:
1. Case summary and risk assessment
2. Key suspicious indicators found
3. Transaction pattern analysis
4. Network/entity connections
5. Recommended disposition (SUSPICIOUS / FALSE_POSITIVE / NEEDS_MORE_INFO)
6. Confidence level (LOW/MEDIUM/HIGH)
"""

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)\((.*?)\)</tool_call>", re.DOTALL)
_FINAL_REPORT_RE = re.compile(r"<final_report>(.*?)</final_report>", re.DOTALL)


def _parse_tool_call(text: str) -> tuple[str, dict] | None:
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    tool_name = m.group(1).strip()
    raw_args = m.group(2).strip()
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        args = {}
    return tool_name, args


def _save_evidence(conn, case_id: str, tool_name: str, args: dict) -> None:
    evidence_id = f"EV-{uuid4().hex[:8].upper()}"
    try:
        conn.execute(
            """INSERT INTO evidence (evidence_id, case_id, tool, query, agent_worker)
               VALUES (?, ?, ?, ?, ?)""",
            (evidence_id, case_id, tool_name, json.dumps(args), "investigator_v1"),
        )
        conn.commit()
    except Exception:
        pass  # evidence saving is best-effort


def run_investigation(case_id: str, conn, stream: bool = False) -> "str | Generator":
    """
    Run a full AML investigation for the given case.
    Returns final narrative report as string, or yields tokens if stream=True.
    Saves evidence rows to DB as tools are called.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Investigate case {case_id}. Begin by retrieving the alert details.",
        },
    ]

    final_report = None

    for _ in range(MAX_ITERATIONS):
        response_text = chat(messages, stream=False)
        assert isinstance(response_text, str)

        messages.append({"role": "assistant", "content": response_text})

        # Check for final report
        fm = _FINAL_REPORT_RE.search(response_text)
        if fm:
            final_report = fm.group(1).strip()
            break

        # Check for tool call
        parsed = _parse_tool_call(response_text)
        if parsed is None:
            # No tool call and no final report — treat remaining text as report
            final_report = response_text.strip()
            break

        tool_name, args = parsed
        _save_evidence(conn, case_id, tool_name, args)

        fn = TOOLS.get(tool_name)
        if fn is None:
            tool_result = {"error": f"Unknown tool: {tool_name}"}
        else:
            try:
                tool_result = fn(conn, **args)
            except Exception as e:
                tool_result = {"error": str(e)}

        result_json = json.dumps(tool_result, default=str)
        messages.append({
            "role": "user",
            "content": f"<tool_result>{result_json}</tool_result>",
        })

    if final_report is None:
        final_report = "Investigation reached maximum iterations without a conclusive report."

    if not stream:
        return final_report

    def _gen() -> Generator:
        # Yield the already-computed report as tokens (word-by-word for streaming UX)
        for word in final_report.split(" "):
            yield word + " "

    return _gen()
