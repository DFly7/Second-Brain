import pytest
from app.agents.tools import AgentTools
from app.models import ChatMessage, ChatSession, Workspace
from sqlalchemy import select


@pytest.fixture
def tools(db_session, workspace_id):
    return AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)


@pytest.mark.asyncio
async def test_search_finds_matching_message(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="Paris road trip plan"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="Route: Lyon → Paris"))
    await db_session.commit()

    result = await tools.search_chat_history("Paris road trip")
    assert "Paris road trip plan" in result
    assert "USER:" in result


@pytest.mark.asyncio
async def test_search_returns_no_match_message(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="Hello world"))
    await db_session.commit()

    result = await tools.search_chat_history("xyznotfound")
    assert result == "No matching messages found in chat history."


@pytest.mark.asyncio
async def test_search_respects_workspace_isolation(db_session, workspace_id):
    ws2 = Workspace(user_id="other-user")
    db_session.add(ws2)
    await db_session.flush()
    other_session = ChatSession(workspace_id=ws2.id)
    db_session.add(other_session)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=other_session.id, role="user", content="secret content xyz"))
    await db_session.commit()

    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    result = await tools.search_chat_history("secret content xyz")
    assert result == "No matching messages found in chat history."


@pytest.mark.asyncio
async def test_search_char_window_excludes_long_neighbours(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="find me please"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="z" * 1000))
    await db_session.commit()

    # With a 50-char window, the 1000-char adjacent message should be excluded
    result = await tools.search_chat_history("find me please", context_window_chars=50)
    assert "find me please" in result
    assert "z" * 100 not in result


@pytest.mark.asyncio
async def test_search_includes_surrounding_context_within_budget(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="before message"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="match here"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="after message"))
    await db_session.commit()

    result = await tools.search_chat_history("match here", context_window_chars=2000)
    assert "before message" in result
    assert "match here" in result
    assert "after message" in result
