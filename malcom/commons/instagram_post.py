"""Instagram Graph API content publishing utilities.

Uses the direct upload (upload_handle) API so images do not need a public URL.

Upload flow:
  1. POST to rupload.facebook.com to upload raw bytes → get upload_handle
  2. Create carousel child containers (is_carousel_item=true, upload_handle=...)
  3. Create carousel container referencing children + caption
  4. Publish the carousel container

Reference:
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing
"""

from __future__ import annotations

import logging

import requests

INSTAGRAM_API_BASE = "https://graph.instagram.com/v22.0"
UPLOAD_API_BASE = "https://rupload.facebook.com/ig-api-upload"

logger = logging.getLogger(__name__)


def upload_image(user_id: str, access_token: str, image_bytes: bytes, filename: str = "image.jpg") -> str:
    """Upload image bytes directly to Instagram using the resumable upload API.

    Returns the upload_handle string to be used in create_carousel_item.
    """
    url = f"{UPLOAD_API_BASE}/{user_id}"
    headers = {
        "Authorization": f"OAuth {access_token}",
        "X-Entity-Length": str(len(image_bytes)),
        "X-Entity-Name": filename,
        "Offset": "0",
        "Content-Type": "image/jpeg",
    }
    response = requests.post(url, headers=headers, data=image_bytes, timeout=60)
    response.raise_for_status()
    data = response.json()
    handle = data.get("h") or data.get("upload_handle")
    if not handle:
        raise ValueError(f"No upload_handle in response: {data}")
    logger.debug(f"Uploaded image {filename!r}: handle={handle!r}")
    return handle


def create_carousel_item(user_id: str, access_token: str, upload_handle: str) -> str:
    """Create a carousel child media container. Returns the container_id."""
    url = f"{INSTAGRAM_API_BASE}/{user_id}/media"
    params = {
        "media_type": "IMAGE",
        "is_carousel_item": "true",
        "upload_handle": upload_handle,
        "access_token": access_token,
    }
    response = requests.post(url, params=params, timeout=30)
    response.raise_for_status()
    container_id = response.json()["id"]
    logger.debug(f"Created carousel item container: {container_id}")
    return container_id


def create_carousel_container(
    user_id: str,
    access_token: str,
    children: list[str],
    caption: str,
) -> str:
    """Create a carousel media container referencing child containers. Returns creation_id."""
    url = f"{INSTAGRAM_API_BASE}/{user_id}/media"
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption[:2200],  # Instagram hard limit
        "access_token": access_token,
    }
    response = requests.post(url, params=params, timeout=30)
    response.raise_for_status()
    creation_id = response.json()["id"]
    logger.debug(f"Created carousel container: {creation_id}")
    return creation_id


def publish_media(user_id: str, access_token: str, creation_id: str) -> str:
    """Publish a media container. Returns the published post_id."""
    url = f"{INSTAGRAM_API_BASE}/{user_id}/media_publish"
    params = {
        "creation_id": creation_id,
        "access_token": access_token,
    }
    response = requests.post(url, params=params, timeout=30)
    response.raise_for_status()
    post_id = response.json()["id"]
    logger.info(f"Published Instagram post: {post_id}")
    return post_id


def post_carousel(
    user_id: str,
    access_token: str,
    images: list[tuple[bytes, str]],  # [(jpeg_bytes, filename), ...]
    caption: str,
) -> str:
    """Execute the full carousel post flow. Returns the published post_id.

    Args:
        user_id: Instagram user ID
        access_token: Valid Instagram access token
        images: List of (jpeg_bytes, filename) for each slide (2-10 images required)
        caption: Post caption (truncated to 2,200 chars)
    """
    if not 2 <= len(images) <= 10:  # noqa: PLR2004
        raise ValueError(f"Carousel requires 2-10 images, got {len(images)}")

    # Step 1 & 2: upload each image and create child containers
    children: list[str] = []
    for jpeg_bytes, filename in images:
        handle = upload_image(user_id, access_token, jpeg_bytes, filename)
        container_id = create_carousel_item(user_id, access_token, handle)
        children.append(container_id)

    # Step 3: create carousel container
    creation_id = create_carousel_container(user_id, access_token, children, caption)

    # Step 4: publish
    return publish_media(user_id, access_token, creation_id)


def build_caption(description: str, playlist_url: str, extra_hashtags: tuple[str, ...] = ()) -> str:
    """Build an Instagram caption from a playlist description.

    Combines the YouTube playlist description, the playlist URL, and
    Instagram-specific hashtags. Truncated to 2,200 characters.
    """
    hashtag_str = " ".join(f"#{tag}" for tag in extra_hashtags)
    parts = [description.strip()]
    parts.append(f"\n▶ {playlist_url}")
    if hashtag_str:
        parts.append(f"\n{hashtag_str}")
    return "\n".join(parts)[:2200]
