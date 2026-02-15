import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_es
from app.models.answer import AnswerCreateRequest, AnswerListResponse, AnswerPublic
from app.models.question import SortOption
from app.utils.auth import get_current_user, get_optional_user

router = APIRouter(tags=["answers"])

PAGE_SIZE = 20


def _hit_to_answer(hit: dict, user_vote: str | None = None) -> AnswerPublic:
    """Convert an ES hit to an AnswerPublic response."""
    src = hit["_source"]
    return AnswerPublic(
        id=hit["_id"],
        body=src["body"],
        question_id=src["question_id"],
        author_id=src["author_id"],
        author_username=src["author_username"],
        upvote_count=src.get("upvote_count", 0),
        downvote_count=src.get("downvote_count", 0),
        score=src.get("score", 0),
        created_at=src["created_at"],
        user_vote=user_vote,
    )


# ──────────────────────────────────────────────────────────────
# POST /questions/{question_id}/answers  — Create an answer
# ──────────────────────────────────────────────────────────────


@router.post(
    "/questions/{question_id}/answers",
    response_model=AnswerPublic,
    status_code=201,
)
async def create_answer(
    question_id: str,
    body: AnswerCreateRequest,
    user: dict = Depends(get_current_user),
):
    """Create an answer to a question. Requires authentication."""
    es = get_es()

    # Validate question exists
    try:
        await es.get(index="questions", id=question_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Question not found")

    now = datetime.now(timezone.utc)

    answer_doc = {
        "body": body.body,
        "question_id": question_id,
        "author_id": user["id"],
        "author_username": user["username"],
        "upvote_count": 0,
        "downvote_count": 0,
        "score": 0,
        "created_at": now.isoformat(),
    }

    result = await es.index(
        index="answers",
        document=answer_doc,
        refresh="wait_for",
    )

    # Increment answer_count on the question + answer_count on the user
    await es.update(
        index="questions",
        id=question_id,
        script={"source": "ctx._source.answer_count += 1"},
    )
    await es.update(
        index="users",
        id=user["id"],
        script={"source": "ctx._source.answer_count += 1"},
    )

    return AnswerPublic(id=result["_id"], **answer_doc)


# ──────────────────────────────────────────────────────────────
# GET /questions/{question_id}/answers  — List answers
# ──────────────────────────────────────────────────────────────


@router.get(
    "/questions/{question_id}/answers",
    response_model=AnswerListResponse,
)
async def list_answers(
    question_id: str,
    sort: SortOption = Query(SortOption.top),
    page: int = Query(1, ge=1),
    user: dict | None = Depends(get_optional_user),
):
    """List answers for a question. Default sort: top (by score)."""
    es = get_es()

    # Validate question exists
    try:
        await es.get(index="questions", id=question_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Question not found")

    from_ = (page - 1) * PAGE_SIZE

    if sort == SortOption.top:
        sort_clause = [
            {"score": {"order": "desc"}},
            {"created_at": {"order": "desc"}},
        ]
    else:
        sort_clause = [{"created_at": {"order": "desc"}}]

    result = await es.search(
        index="answers",
        query={"term": {"question_id": question_id}},
        sort=sort_clause,
        from_=from_,
        size=PAGE_SIZE,
    )

    total = result["hits"]["total"]["value"]
    total_pages = max(1, math.ceil(total / PAGE_SIZE))

    # If authenticated, fetch the user's votes on these answers
    answers = result["hits"]["hits"]
    user_votes = {}

    if user and answers:
        answer_ids = [h["_id"] for h in answers]
        vote_ids = [f"vote_{user['id']}_{aid}" for aid in answer_ids]
        try:
            votes_result = await es.mget(index="votes", ids=vote_ids)
            for doc in votes_result["docs"]:
                if doc.get("found"):
                    target_id = doc["_source"]["target_id"]
                    user_votes[target_id] = doc["_source"]["vote_type"]
        except Exception:
            pass

    return AnswerListResponse(
        answers=[
            _hit_to_answer(h, user_vote=user_votes.get(h["_id"]))
            for h in answers
        ],
        page=page,
        total_pages=total_pages,
    )


# ──────────────────────────────────────────────────────────────
# GET /answers/{answer_id}  — Single answer by ID
# ──────────────────────────────────────────────────────────────


@router.get("/answers/{answer_id}", response_model=AnswerPublic)
async def get_answer(
    answer_id: str,
    user: dict | None = Depends(get_optional_user),
):
    """Get a single answer by ID. Public endpoint."""
    es = get_es()

    try:
        result = await es.get(index="answers", id=answer_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Answer not found")

    # Check if authenticated user has voted on this answer
    user_vote = None
    if user:
        try:
            vote_doc = await es.get(
                index="votes", id=f"vote_{user['id']}_{answer_id}"
            )
            user_vote = vote_doc["_source"]["vote_type"]
        except Exception:
            pass

    return _hit_to_answer(result, user_vote=user_vote)
