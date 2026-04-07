"""Instagram Graph API content publishing utilities (Instagram with Instagram Login).

The Instagram Platform `image_url` flow is the only documented path for publishing
static images on the IGwIL API surface — `rupload.facebook.com/ig-api-upload` is
reels/video only and rejects image uploads with `400 NotAuthorizedError`.

Each carousel slide must therefore be hosted on a publicly fetchable HTTPS URL
before container creation. We host on catbox.moe (free, no signup, persistent
URLs, accepts JPEG up to 200 MB).

Publish flow:
  1. Upload each JPEG to catbox.moe → public HTTPS URL
  2. Create child container per slide (`is_carousel_item=true`, `image_url=...`)
  3. Poll each child container until `status_code == FINISHED`
  4. Create the parent CAROUSEL container with the children IDs and caption
  5. Poll the parent container until `status_code == FINISHED`
  6. Publish via `/{ig-user-id}/media_publish`

Reference:
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing
"""

from __future__ import annotations

import logging
import time

import requests

from commons.functions import upload_to_catbox

INSTAGRAM_API_BASE = "https://graph.instagram.com/v22.0"

# Container status polling
CONTAINER_POLL_INTERVAL_SECONDS = 3
CONTAINER_POLL_MAX_ATTEMPTS = 20  # 20 * 3s = 60s max wait per container
CONTAINER_STATUS_FINISHED = "FINISHED"
CONTAINER_STATUS_IN_PROGRESS = "IN_PROGRESS"

logger = logging.getLogger(__name__)


class InstagramContainerError(RuntimeError):
    """Raised when an Instagram media container fails to reach FINISHED status."""


def create_carousel_item(user_id: str, access_token: str, image_url: str) -> str:
    """Create a carousel child media container from a public image URL. Returns container_id."""
    url = f"{INSTAGRAM_API_BASE}/{user_id}/media"
    params = {
        "media_type": "IMAGE",
        "is_carousel_item": "true",
        "image_url": image_url,
        "access_token": access_token,
    }
    response = requests.post(url, params=params, timeout=30)
    response.raise_for_status()
    container_id = response.json()["id"]
    logger.debug(f"Created carousel item container: {container_id} (image_url={image_url})")
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


def wait_for_container_finished(container_id: str, access_token: str) -> None:
    """Poll a media container until status_code == FINISHED. Raises on ERROR or timeout."""
    url = f"{INSTAGRAM_API_BASE}/{container_id}"
    params = {"fields": "status_code", "access_token": access_token}
    for attempt in range(1, CONTAINER_POLL_MAX_ATTEMPTS + 1):
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        status = response.json().get("status_code", "")
        if status == CONTAINER_STATUS_FINISHED:
            logger.debug(f"Container {container_id} FINISHED after {attempt} poll(s)")
            return
        if status and status != CONTAINER_STATUS_IN_PROGRESS:
            raise InstagramContainerError(f"Container {container_id} failed with status_code={status!r}")
        time.sleep(CONTAINER_POLL_INTERVAL_SECONDS)
    raise InstagramContainerError(
        f"Container {container_id} did not reach FINISHED within "
        f"{CONTAINER_POLL_MAX_ATTEMPTS * CONTAINER_POLL_INTERVAL_SECONDS}s"
    )


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

    # Step 1: upload each image to catbox to obtain a public HTTPS URL
    image_urls: list[tuple[str, str]] = []
    for jpeg_bytes, filename in images:
        public_url = upload_to_catbox(jpeg_bytes, filename)
        image_urls.append((public_url, filename))

    # Step 2: create one child container per uploaded image
    children: list[str] = []
    for public_url, _filename in image_urls:
        container_id = create_carousel_item(user_id, access_token, public_url)
        children.append(container_id)

    # Step 3: wait for each child container to finish (Meta fetches the image_url asynchronously)
    for container_id in children:
        wait_for_container_finished(container_id, access_token)

    # Step 4: create the parent CAROUSEL container
    creation_id = create_carousel_container(user_id, access_token, children, caption)

    # Step 5: wait for the parent container to finish
    wait_for_container_finished(creation_id, access_token)

    # Step 6: publish
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
