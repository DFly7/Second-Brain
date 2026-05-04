# api/tests/test_prompts.py
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "app" / "agents" / "prompts"

STATIC_PROMPTS = [
    "query.md",
    "edit.md",
    "ingest_small.md",
    "ingest_large.md",
    "health.md",
    "chat_monitor.md",
    "sub_agent.md",
    "run_context_wrapper.md",
]


def test_all_prompt_files_exist():
    for name in STATIC_PROMPTS:
        assert (PROMPTS_DIR / name).exists(), f"Missing prompt file: {name}"


def test_static_prompts_are_non_empty():
    for name in STATIC_PROMPTS:
        text = (PROMPTS_DIR / name).read_text().strip()
        assert text, f"Prompt file is empty: {name}"


def test_agent_modules_load_prompts():
    from app.agents import query_agent, health_agent, chat_monitor, sub_agent, edit_agent
    assert query_agent.SYSTEM_PROMPT.strip()
    assert health_agent.SYSTEM_PROMPT.strip()
    assert chat_monitor.SYSTEM_PROMPT.strip()
    assert sub_agent.SYSTEM_PROMPT.strip()
    assert edit_agent.SYSTEM_PROMPT.strip()


def test_ingest_agent_loads_both_prompts():
    from app.agents import ingest_agent
    assert ingest_agent.SYSTEM_PROMPT_SMALL.strip()
    assert ingest_agent.SYSTEM_PROMPT_LARGE.strip()
    assert ingest_agent.SYSTEM_PROMPT_SMALL != ingest_agent.SYSTEM_PROMPT_LARGE
