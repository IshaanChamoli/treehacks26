from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_es

# HTTPBearer extracts the token from "Authorization: Bearer <token>"
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Validate an ES API key and return the user.

    Flow:
    1. Agent sends: Authorization: Bearer <encoded_es_api_key>
    2. We call ES security.authenticate() with that key to validate it
    3. ES validates the key (checks it's not expired/invalidated)
    4. We get the key ID from the auth response
    5. We fetch the key's metadata via the admin client (get_api_key)
       — this contains our user_id and username
    6. We fetch the full user document from the users index
    """
    es = get_es()
    encoded_key = credentials.credentials

    # Step 1: Validate the API key against Elasticsearch's native security
    try:
        auth_info = await es.options(api_key=encoded_key).security.authenticate()
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Step 2: Get the key ID from the authenticate response
    api_key_id = auth_info.get("api_key", {}).get("id")
    if not api_key_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Step 3: Fetch the key's metadata via the admin client
    # (Serverless doesn't return metadata in authenticate(), so we use get_api_key)
    try:
        key_info = await es.security.get_api_key(id=api_key_id)
        metadata = key_info["api_keys"][0]["metadata"]
    except Exception:
        raise HTTPException(status_code=401, detail="Could not retrieve API key metadata")

    user_id = metadata.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key: missing user metadata")

    # Step 4: Fetch the full user profile from the users index
    try:
        user_doc = await es.get(index="users", id=user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    return {"id": user_id, **user_doc["_source"]}


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
) -> dict | None:
    """
    Optionally validate an API key. Returns None if no auth header provided.
    Used for endpoints where auth is optional (e.g. listing questions shows
    user_vote if authenticated, but works without auth too).
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None
