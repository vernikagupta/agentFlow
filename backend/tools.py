"""
agentFlow tools — catalog, registry, and executors.

How this file fits the pipeline
-------------------------------
  agent.py (tool selector Groq)  →  picks tool name e.g. "web_search"
  get_tools()                  →  TOOL_DEFINITIONS sent to Groq (name + description only)
  run_tool(name, ...)          →  TOOL_REGISTRY[name](...) runs the real implementation
  success                      →  task.result = {success: true, tool_output: {...}}
  ToolExecutionError           →  agent.py sets task.status=failed, workflow still completes

Tools today
-----------
  web_search  — Tavily API (real results only, never fabricated)
  summarize   — Groq LLM; output grounded in input text only (guardrails)

Environment (.env)
------------------
  GROQ_API_KEY, GROQ_MODEL    summarize tool (same as agent.py orchestration)
  TAVILY_API_KEY              required for web_search
  TAVILY_MAX_RESULTS          optional, default 5
  TAVILY_SEARCH_DEPTH         optional, default "basic"
  SUMMARIZE_MAX_INPUT_CHARS   optional, default 32000
  SUMMARIZE_MAX_BULLETS       optional, default 6
  SUMMARIZE_MIN_BULLET_OVERLAP optional, default 0.35 (guardrail word overlap)
  AGENTFLOW_DEBUG=0           turns off [DEBUG] prints in this file
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from groq import Groq

# Each tool returns a dict stored in tasks.result JSONB as tool_output.
ToolFn = Callable[..., dict[str, Any]]


class ToolExecutionError(Exception):
    """
    Tool failed (API error, missing config, bad response).

    Not raised to the top of run_workflow — agent.py catches per task:
      task.status = "failed"
      task.result = {success: false, error: {...}, tool_output: null}
    Other tasks and the final workflow summary still run.
    """

    def __init__(
        self,
        message: str,
        *,
        tool_name: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.details = details or {}


def _debug(step: str, **fields: Any) -> None:
    """Terminal-only IN/OUT logging; disable with AGENTFLOW_DEBUG=0 in .env."""
    if os.getenv("AGENTFLOW_DEBUG", "1").strip().lower() in ("0", "false", "no"):
        return
    print(f"\n[DEBUG] --- {step} ---")
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            print(f"  {key}:")
            print(json.dumps(value, indent=2, default=str))
        else:
            print(f"  {key}: {value!r}")


# --- Catalog for Groq tool-selector (names must match TOOL_REGISTRY keys) -------

TOOL_DEFINITIONS: list[dict[str, str]] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for facts, companies, news, or references via Tavily. "
            "Use when the task needs external information or sources."
        ),
    },
    {
        "name": "summarize",
        "description": (
            "Summarize provided text into a short summary and bullet list. "
            "Use only when the subtask is to condense or report on text already in the task description "
            "(not for live web search — use web_search first if facts are missing)."
        ),
    },
]


# --- web_search (Tavily) -------------------------------------------------------

def _format_tavily_results(api_response: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert Tavily response["results"] to our stable API shape.

    Tavily fields: title, url, content (we expose as snippet), optional score.
    Skips empty rows — does not invent filler text.
    """
    raw_results = api_response.get("results")
    if not isinstance(raw_results, list):
        return []

    formatted: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        snippet = (item.get("content") or "").strip()
        if not title and not url and not snippet:
            continue
        entry: dict[str, Any] = {
            "title": title,
            "url": url,
            "snippet": snippet,
        }
        score = item.get("score")
        if score is not None:
            entry["score"] = score
        formatted.append(entry)
    return formatted


def web_search(*, query: str) -> dict[str, Any]:
    """
    Live web search via Tavily Python SDK.

    Returns only data from the API. Zero hits → result_count 0 and results [] (not an error).

    Success JSON (goes in task.result.tool_output):
      {
        "tool": "web_search",
        "success": true,
        "query": "...",
        "result_count": N,
        "results": [{"title", "url", "snippet", "score"?}, ...]
      }

    Raises ToolExecutionError when:
      - query is empty
      - TAVILY_API_KEY missing
      - tavily-python not installed
      - Tavily HTTP/API failure
      - response is not a dict
    """
    query = query.strip()
    if not query:
        raise ToolExecutionError(
            "Search query is empty",
            tool_name="web_search",
        )

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise ToolExecutionError(
            "TAVILY_API_KEY is missing — add it to .env",
            tool_name="web_search",
        )

    max_results = int(os.getenv("TAVILY_MAX_RESULTS", "5"))

    try:
        from tavily import TavilyClient
    except ImportError as exc:
        raise ToolExecutionError(
            "tavily package not installed — run: pip install tavily-python",
            tool_name="web_search",
            details={"import_error": str(exc)},
        ) from exc

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
        )
    except Exception as exc:
        raise ToolExecutionError(
            f"Tavily search failed: {exc}",
            tool_name="web_search",
            details={"query": query, "max_results": max_results},
        ) from exc

    if not isinstance(response, dict):
        raise ToolExecutionError(
            "Tavily returned an unexpected response type",
            tool_name="web_search",
            details={"response_type": type(response).__name__},
        )

    results = _format_tavily_results(response)
    return {
        "tool": "web_search",
        "success": True,
        "query": response.get("query") or query,
        "result_count": len(results),
        "results": results,
    }


# --- summarize (Groq — source-grounded) ------------------------------------------

_SUMMARIZE_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
        "is", "are", "was", "were", "be", "been", "being", "with", "as", "by", "from",
        "that", "this", "it", "its", "their", "they", "we", "you", "your",
    }
)

SUMMARIZE_SYSTEM = """You are a strict summarization tool for agentFlow.
You receive SOURCE TEXT only. Condense it — never add outside knowledge.

Mandatory rules:
1. Use ONLY facts, names, numbers, and claims explicitly present in SOURCE TEXT.
2. Do NOT invent, infer, assume, or use general world knowledge not in the source.
3. If the source is short or vague, write a minimal honest summary; do not pad with filler.
4. Return ONLY valid JSON (no markdown fences), exactly:
   {"summary": "1-3 sentences", "bullets": ["point 1", "point 2"]}
5. "summary": 1-3 sentences, plain language, every claim traceable to the source.
6. "bullets": 2-6 short bullets; each bullet = one point from the source only.
7. If nothing can be extracted, use "bullets": [] and state that in summary."""

def _strip_json_fences(raw: str) -> str:
    """Remove optional ```json markdown wrappers from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    return text


def _significant_words(text: str) -> list[str]:
    """Content words for overlap guardrail (not stopwords, len > 2)."""
    return [
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) > 2 and w not in _SUMMARIZE_STOPWORDS
    ]


def _overlap_ratio(fragment: str, source_word_set: set[str]) -> float:
    words = _significant_words(fragment)
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in source_word_set)
    return hits / len(words)


def _fragment_grounded_in_source(fragment: str, source: str, *, min_overlap: float) -> bool:
    """
    Guardrail: bullet/summary must share enough vocabulary with source text.
    Paraphrases often share root words; invented facts usually do not.
    """
    stripped = fragment.strip()
    if not stripped:
        return False
    if stripped.lower() in source.lower():
        return True
    source_words = set(_significant_words(source))
    if not source_words:
        return len(stripped) <= len(source) + 20
    return _overlap_ratio(stripped, source_words) >= min_overlap


def _parse_summarize_llm_json(raw: str) -> dict[str, Any]:
    """Parse Groq JSON; enforce required keys and types."""
    try:
        data = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(
            "Groq summarize response is not valid JSON",
            tool_name="summarize",
            details={"parse_error": str(exc), "raw_preview": raw[:500]},
        ) from exc

    if not isinstance(data, dict):
        raise ToolExecutionError(
            "Summarize JSON must be an object",
            tool_name="summarize",
            details={"response_type": type(data).__name__},
        )

    summary = data.get("summary")
    bullets = data.get("bullets")

    if not summary or not isinstance(summary, str):
        raise ToolExecutionError(
            "Summarize JSON must contain a non-empty string 'summary'",
            tool_name="summarize",
        )
    if not isinstance(bullets, list):
        raise ToolExecutionError(
            "Summarize JSON must contain a 'bullets' array",
            tool_name="summarize",
        )

    cleaned_bullets: list[str] = []
    for index, item in enumerate(bullets):
        if not isinstance(item, str):
            raise ToolExecutionError(
                f"Bullet at index {index} must be a string",
                tool_name="summarize",
            )
        bullet = item.strip()
        if bullet:
            cleaned_bullets.append(bullet)

    summary = summary.strip()
    if not summary:
        raise ToolExecutionError(
            "Summarize JSON 'summary' cannot be empty after strip",
            tool_name="summarize",
        )

    max_bullets = int(os.getenv("SUMMARIZE_MAX_BULLETS", "6"))
    if len(cleaned_bullets) > max_bullets:
        raise ToolExecutionError(
            f"Too many bullets ({len(cleaned_bullets)}); max is {max_bullets}",
            tool_name="summarize",
            details={"bullet_count": len(cleaned_bullets), "max_bullets": max_bullets},
        )

    return {"summary": summary, "bullets": cleaned_bullets}


def _apply_summarize_guardrails(
    parsed: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """
    Reject hallucinated output: summary and each bullet must overlap source vocabulary.
    """
    min_overlap = float(os.getenv("SUMMARIZE_MIN_BULLET_OVERLAP", "0.35"))
    summary = parsed["summary"]
    bullets: list[str] = parsed["bullets"]

    if not _fragment_grounded_in_source(summary, source, min_overlap=min_overlap * 0.8):
        raise ToolExecutionError(
            "Guardrail: summary is not grounded in source text (possible hallucination)",
            tool_name="summarize",
            details={
                "guardrail": "summary_overlap",
                "min_overlap": min_overlap * 0.8,
                "summary_preview": summary[:200],
            },
        )

    rejected: list[dict[str, str]] = []
    grounded: list[str] = []
    for bullet in bullets:
        if _fragment_grounded_in_source(bullet, source, min_overlap=min_overlap):
            grounded.append(bullet)
        else:
            rejected.append({"bullet": bullet[:200]})

    if rejected and not grounded:
        raise ToolExecutionError(
            "Guardrail: all bullets failed source overlap check (possible hallucination)",
            tool_name="summarize",
            details={
                "guardrail": "bullet_overlap",
                "min_overlap": min_overlap,
                "rejected_count": len(rejected),
                "rejected": rejected,
            },
        )

    if rejected:
        _debug(
            "summarize guardrail dropped bullets",
            rejected=rejected,
            kept_count=len(grounded),
        )

    return {"summary": summary, "bullets": grounded}


def _call_groq_summarize(*, source_text: str) -> str:
    """Groq chat completion for summarize — uses GROQ_API_KEY and GROQ_MODEL from .env."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ToolExecutionError(
            "GROQ_API_KEY is missing — add it to .env",
            tool_name="summarize",
        )

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    temperature = float(os.getenv("SUMMARIZE_TEMPERATURE", "0.1"))
    _debug("summarize Groq request", model=model, input_length=len(source_text))

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUMMARIZE_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "Summarize the following SOURCE TEXT. "
                        "Do not add any information not present below.\n\n"
                        f"--- SOURCE TEXT START ---\n{source_text}\n--- SOURCE TEXT END ---"
                    ),
                },
            ],
            temperature=temperature,
        )
    except Exception as exc:
        raise ToolExecutionError(
            f"Groq summarize request failed: {exc}",
            tool_name="summarize",
            details={"model": model},
        ) from exc

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise ToolExecutionError(
            "Groq returned empty summarize content",
            tool_name="summarize",
            details={"model": model},
        )
    return raw


def summarize(*, text: str) -> dict[str, Any]:
    """
    Summarize source text via Groq (same API key/model as agent.py).

    Guardrails:
      - System prompt: source-only, no outside knowledge
      - Prompt requires JSON; Python parses and validates shape
      - Post-parse overlap check on summary + bullets

    Success JSON (task.result.tool_output):
      {
        "tool": "summarize",
        "success": true,
        "input_length": N,
        "summary": "...",
        "bullets": ["...", ...]
      }

    Raises ToolExecutionError on empty input, oversize input, Groq errors,
    bad JSON, schema violations, or guardrail rejection.
    """
    source = text.strip()
    if not source:
        raise ToolExecutionError(
            "Summarize input text is empty",
            tool_name="summarize",
        )

    max_chars = int(os.getenv("SUMMARIZE_MAX_INPUT_CHARS", "32000"))
    if len(source) > max_chars:
        raise ToolExecutionError(
            f"Source text exceeds SUMMARIZE_MAX_INPUT_CHARS ({max_chars})",
            tool_name="summarize",
            details={"input_length": len(source), "max_chars": max_chars},
        )

    _debug("summarize IN", input_length=len(source), source_preview=source[:300])

    raw = _call_groq_summarize(source_text=source)
    _debug("summarize Groq raw", llm_response=raw[:2000])

    parsed = _parse_summarize_llm_json(raw)
    grounded = _apply_summarize_guardrails(parsed, source=source)

    output = {
        "tool": "summarize",
        "success": True,
        "input_length": len(source),
        "summary": grounded["summary"],
        "bullets": grounded["bullets"],
    }
    _debug("summarize OUT", tool_output=output)
    return output


# --- Registry: Groq returns name string → Python runs matching function --------

TOOL_REGISTRY: dict[str, ToolFn] = {
    "web_search": web_search,
    "summarize": summarize,
}


def get_tools() -> tuple[list[dict[str, str]], dict[str, ToolFn]]:
    """
    Called once per workflow in agent._select_and_run_tools.

    Returns:
        catalog  — copy of TOOL_DEFINITIONS for the Groq tool-selector prompt
        registry — copy of TOOL_REGISTRY for run_tool() execution
    """
    catalog = list(TOOL_DEFINITIONS)
    registry = dict(TOOL_REGISTRY)
    _debug(
        "get_tools()",
        catalog_for_groq=catalog,
        registry_tool_names=list(registry.keys()),
    )
    return catalog, registry


def run_tool(tool_name: str, *, task_name: str, task_description: str | None) -> dict[str, Any]:
    """
    Run the tool Groq selected for one task.

    Input context: task_description if set, else task_name (passed as query/text).

    On success: returns tool-specific dict (see web_search / summarize docstrings).
    On failure: raises ToolExecutionError — agent.py catches and marks task failed.

    Does not catch exceptions here so agent can log execution_logs event_type=error.
    """
    registry = TOOL_REGISTRY
    if tool_name not in registry:
        allowed = ", ".join(sorted(registry))
        raise ToolExecutionError(
            f"Unknown tool {tool_name!r}; allowed: {allowed}",
            tool_name=tool_name,
        )

    fn = registry[tool_name]
    context = (task_description or task_name).strip()
    _debug(
        "run_tool IN",
        tool_name=tool_name,
        task_name=task_name,
        context=context,
    )

    # Different tools use different keyword args; names must match TOOL_REGISTRY.
    if tool_name == "web_search":
        output = fn(query=context)
    elif tool_name == "summarize":
        output = fn(text=context)
    else:
        output = fn(query=context)

    _debug("run_tool OUT", tool_name=tool_name, tool_output=output)
    return output
