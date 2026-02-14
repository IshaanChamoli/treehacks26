from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_es
from app.models.forum import ForumCreateRequest, ForumPublic
from app.utils.auth import get_current_user

router = APIRouter(prefix="/forums", tags=["forums"])


@router.post("/", response_model=ForumPublic, status_code=201)
async def create_forum(
    body: ForumCreateRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new forum. Requires authentication."""
    es = get_es()

    # Check if forum name already exists (keyword field = exact match)
    existing = await es.search(
        index="forums",
        query={"term": {"name": body.name}},
        size=1,
    )
    if existing["hits"]["total"]["value"] > 0:
        raise HTTPException(status_code=409, detail="Forum name already exists")

    now = datetime.now(timezone.utc)
    forum_doc = {
        "name": body.name,
        "description": body.description,
        "created_by": user["id"],
        "created_by_username": user["username"],
        "question_count": 0,
        "created_at": now.isoformat(),
    }

    result = await es.index(index="forums", document=forum_doc, refresh="wait_for")

    return ForumPublic(id=result["_id"], **forum_doc, created_at=now)


@router.get("/", response_model=list[ForumPublic])
async def list_forums(
    search: str | None = Query(None, description="Search forums by name"),
):
    """List all forums, optionally filtered by search query. Public endpoint."""
    es = get_es()

    if search:
        # Wildcard search on the keyword field (case-sensitive exact match)
        # For keyword fields we use wildcard query
        query = {"wildcard": {"name": {"value": f"*{search}*", "case_insensitive": True}}}
    else:
        query = {"match_all": {}}

    result = await es.search(
        index="forums",
        query=query,
        sort=[{"question_count": {"order": "desc"}}],
        size=50,
    )

    return [
        ForumPublic(id=hit["_id"], **hit["_source"])
        for hit in result["hits"]["hits"]
    ]


@router.get("/{forum_id}", response_model=ForumPublic)
async def get_forum(forum_id: str):
    """Get a specific forum by ID. Public endpoint."""
    es = get_es()

    try:
        result = await es.get(index="forums", id=forum_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Forum not found")

    return ForumPublic(id=result["_id"], **result["_source"])
