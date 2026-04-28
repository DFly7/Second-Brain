import json

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from litellm import aembedding

from app.config import settings
from app.models import Page


def parse_search_results(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        if row["id"] not in seen or row["score"] > seen[row["id"]]["score"]:
            seen[row["id"]] = row
    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)


async def embed(text_input: str) -> list[float]:
    resp = await aembedding(
        model="gemini/gemini-embedding-001",
        input=[text_input],
        dimensions=1536,
    )
    emb = resp.data[0]["embedding"]
    if isinstance(emb, str):
        emb = json.loads(emb)
    return [float(x) for x in emb]


async def _workspace_has_page_embeddings(session: AsyncSession, workspace_id: str) -> bool:
    r = await session.execute(
        select(func.count())
        .select_from(Page)
        .where(Page.workspace_id == workspace_id, Page.embedding.is_not(None))
    )
    return (r.scalar_one() or 0) > 0


async def search_pages(
    session: AsyncSession,
    workspace_id: str,
    query: str,
    limit: int = 5,
) -> list[dict]:
    use_vector = settings.vector_search_enabled and await _workspace_has_page_embeddings(
        session, workspace_id
    )

    if not use_vector:
        sql = text("""
            SELECT id, slug, title, summary,
                   ts_rank(
                       to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(body_md,'')),
                       plainto_tsquery('english', :query)
                   ) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(body_md,''))
                  @@ plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)
        result = await session.execute(
            sql, {"query": query, "ws_id": workspace_id, "limit": limit}
        )
        return [dict(row._mapping) for row in result]

    query_embedding = await embed(query)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    sql = text("""
        WITH fts AS (
            SELECT id, slug, title, summary,
                   ts_rank(
                       to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(body_md,'')),
                       plainto_tsquery('english', :query)
                   ) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(body_md,''))
                  @@ plainto_tsquery('english', :query)
        ),
        vec AS (
            SELECT id, slug, title, summary,
                   1 - (embedding <=> :embedding::vector) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND embedding IS NOT NULL
        ),
        combined AS (
            SELECT id, slug, title, summary, score FROM fts
            UNION ALL
            SELECT id, slug, title, summary, score FROM vec
        )
        SELECT id, slug, title, summary, MAX(score) as score
        FROM combined
        GROUP BY id, slug, title, summary
        ORDER BY score DESC
        LIMIT :limit
    """)
    result = await session.execute(
        sql,
        {
            "query": query,
            "ws_id": workspace_id,
            "embedding": embedding_str,
            "limit": limit,
        },
    )
    return [dict(row._mapping) for row in result]
