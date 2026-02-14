from elasticsearch import AsyncElasticsearch

from app.config import settings

es_client: AsyncElasticsearch | None = None


async def init_es() -> AsyncElasticsearch:
    """Initialize the async Elasticsearch client (called at app startup)."""
    global es_client
    es_client = AsyncElasticsearch(
        settings.elasticsearch_url,
        api_key=settings.elasticsearch_api_key,
        request_timeout=30,
        max_retries=3,
        retry_on_timeout=True,
    )
    return es_client


async def close_es():
    """Close the Elasticsearch client (called at app shutdown)."""
    global es_client
    if es_client:
        await es_client.close()
        es_client = None


def get_es() -> AsyncElasticsearch:
    """Get the current Elasticsearch client instance."""
    if es_client is None:
        raise RuntimeError("Elasticsearch client not initialized")
    return es_client
