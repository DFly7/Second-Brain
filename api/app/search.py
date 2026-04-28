import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from litellm import aembedding


def parse_search_results(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        if row["id"] not in seen or row["score"] > seen[row["id"]]["score"]:
            seen[row["id"]] = row
    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)


async def embed(text_input: str) -> list[float]:
    resp = await aembedding(model="gemini/text-embedding-004", input=[text_input])
    emb = resp.data[0]["embedding"]
    if isinstance(emb, str):
        emb = json.loads(emb)
    return [float(x) for x in emb]


async def search_pages(
    session: AsyncSession,
    workspace_id: str,
    query: str,
    limit: int = 5,
) -> list[dict]:
    query_embedding = await embed(query)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    sql = text("""
        WITH fts AS (
            SELECT id, slug, title, summary,
                   ts_rank(tsv, plainto_tsquery('english', :query)) AS score
            FROM pages
            WHERE workspace_id = :ws_id
              AND tsv @@ plainto_tsquery('english', :query)
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
