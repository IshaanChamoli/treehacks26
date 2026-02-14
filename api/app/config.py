from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    elasticsearch_url: str
    elasticsearch_api_key: str

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
