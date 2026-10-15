from fastapi import APIRouter, Header, HTTPException, Request, status

from .object_storage import LocalObjectStorage, ObjectStorageError, object_storage


router = APIRouter(prefix="/storage", tags=["object storage"])


@router.put("/uploads/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def local_upload(
    attachment_id: str,
    request: Request,
    token: str = Header(min_length=20, alias="X-FlowForge-Storage-Token"),
) -> None:
    if not isinstance(object_storage, LocalObjectStorage):
        raise HTTPException(status_code=404, detail="Storage route not found")
    try:
        authorization = object_storage.verify_upload_token(attachment_id, token)
    except ObjectStorageError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    expected_type = str(authorization["content_type"])
    actual_type = (request.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]
    if actual_type != expected_type:
        raise HTTPException(status_code=400, detail="Attachment content type changed during upload")
    content = await request.body()
    if not content or len(content) > int(authorization["max_bytes"]):
        raise HTTPException(status_code=413, detail="Attachment size is invalid")
    await object_storage.put(str(authorization["storage_key"]), content, expected_type)
