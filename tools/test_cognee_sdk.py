"""Quick test: Cognee SDK add + search using SQLite (no server needed)."""

import os

# Set env before import
os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"
os.environ["CACHING"] = "false"
os.environ["DB_PROVIDER"] = "sqlite"
os.environ["COGNEE_SKIP_CONNECTION_TEST"] = "true"

# LLM via OpenCode Go（唯一允许的 AI API，旧 proxy 已过期）
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_MODEL"] = "openai/deepseek-v4-flash"
os.environ["LLM_ENDPOINT"] = "https://opencode.ai/zen/go/v1"
os.environ["LLM_API_KEY"] = "YOUR_DEEPSEEK_API_KEY"

# JSON instructor mode avoids forced tool_choice (Console Go doesn't support it)
os.environ["LLM_INSTRUCTOR_MODE"] = "json_mode"

# Embedding via local fastembed（OpenCode Go 无 embedding 端点）
os.environ["EMBEDDING_PROVIDER"] = "fastembed"
os.environ["EMBEDDING_MODEL"] = "BAAI/bge-small-en-v1.5"
os.environ["EMBEDDING_DIMENSIONS"] = "384"

import asyncio
import cognee
from cognee.modules.search.types import SearchType


async def main():
    print("Cognee version:", getattr(cognee, "__version__", "unknown"))

    # Add a sample document
    text = "Apple Inc. is a technology company. It designs iPhones and Macs."
    print(f"Adding: {text[:50]}...")
    await cognee.add(text)
    print("Added successfully.")

    # Cognify: process into knowledge graph (chunk, embed, summarize)
    print("Cognifying...")
    await cognee.cognify()
    print("Cognify done.")

    # Search
    print("Searching...")
    results = await cognee.search("Apple products", query_type=SearchType.SUMMARIES)
    print(f"Results: {results}")


if __name__ == "__main__":
    asyncio.run(main())
