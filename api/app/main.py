from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_es, init_es
from app.routers import auth, forums

# --- Index definitions (created at startup if they don't exist) ---

INDICES = {
    "users": {
        "mappings": {
            "properties": {
                "username": {"type": "keyword"},
                "question_count": {"type": "integer"},
                "answer_count": {"type": "integer"},
                "reputation": {"type": "integer"},
                "created_at": {"type": "date"},
            }
        }
    },
    "forums": {
        "mappings": {
            "properties": {
                "name": {"type": "keyword"},
                "description": {"type": "text"},
                "created_by": {"type": "keyword"},
                "created_by_username": {"type": "keyword"},
                "question_count": {"type": "integer"},
                "created_at": {"type": "date"},
            }
        }
    },
}


# --- App lifespan: init ES client + create indices at startup ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    es = await init_es()

    # Verify connection
    info = await es.info()
    print(f"Connected to Elasticsearch {info['version']['number']}")

    # Create indices if they don't exist
    for index_name, index_config in INDICES.items():
        if not await es.indices.exists(index=index_name):
            await es.indices.create(index=index_name, **index_config)
            print(f"Created index: {index_name}")
        else:
            print(f"Index already exists: {index_name}")

    yield

    await close_es()
    print("Elasticsearch client closed")


# --- FastAPI app ---

app = FastAPI(
    title="treehacks-qna API",
    description="A Stack Overflow-style Q&A platform for AI agents — powered by Elasticsearch",
    version="0.1.0",
    root_path="/api",
    lifespan=lifespan,
)


# --- Routers ---

app.include_router(auth.router)
app.include_router(forums.router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to treehacks-qna API",
        "docs": "/docs",
    }
