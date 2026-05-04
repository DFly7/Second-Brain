from app.agents.prompt_render import render_system_prompt


def test_render_system_prompt_has_block_and_local_time_line():
    out = render_system_prompt("PROMPT_BODY", model=None)
    assert "<run_context>" in out
    assert "</run_context>" in out
    assert "Current date and time (server local):" in out
    assert out.endswith("PROMPT_BODY")


def test_render_system_prompt_includes_model_when_given():
    out = render_system_prompt("X", model="anthropic/claude-3-5-sonnet")
    assert "Model: anthropic/claude-3-5-sonnet" in out
