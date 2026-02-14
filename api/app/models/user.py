from datetime import datetime

from pydantic import BaseModel, Field


class UserRegisterRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=6,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Username (6-30 chars, alphanumeric with _ and -)",
    )


class UserPublic(BaseModel):
    id: str
    username: str
    question_count: int = 0
    answer_count: int = 0
    reputation: int = 0
    created_at: datetime


class UserRegisterResponse(BaseModel):
    user: UserPublic
    api_key: str
    message: str = "Welcome to treehacks-qna! Save your API key — it won't be shown again."
