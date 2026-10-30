"""Images on tasks and memory: what is accepted, where it shows, and what an agent sees."""

import base64
import struct
import zlib
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.images import sniff
from tests.conftest import app_client
from tests.test_mcp import agent, call

pytestmark = pytest.mark.anyio


def png(width: int = 3, height: int = 2) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height)))
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


async def project(client: AsyncClient, tmp_path: Path) -> str:
    response = await client.post("/api/projects", json={"name": "Pix", "root_path": str(tmp_path)})
    return response.json()["id"]


async def attach(client: AsyncClient, url: str, data: bytes, name: str = "shot.png"):
    return await client.post(f"{url}/images", params={"filename": name}, content=data)


def test_sniff_reads_the_real_type_and_size() -> None:
    assert sniff(png(7, 5)) == ("image/png", 7, 5)
    assert sniff(b"GIF89a" + struct.pack("<HH", 4, 9) + b"\x00" * 8) == ("image/gif", 4, 9)
    jpeg = (
        b"\xff\xd8\xff\xe0\x00\x04ab\xff\xc0\x00\x0b\x08" + struct.pack(">HH", 30, 40) + b"\x00" * 8
    )
    assert sniff(jpeg) == ("image/jpeg", 40, 30)
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 8 + (99).to_bytes(3, "little") * 2
    assert sniff(webp) == ("image/webp", 100, 100)


async def test_people_attach_view_and_remove_images(client: AsyncClient, tmp_path: Path) -> None:
    pid = await project(client, tmp_path)
    task = (await client.post(f"/api/projects/{pid}/tasks", json={"title": "Fix menu"})).json()
    url = f"/api/projects/{pid}/tasks/{task['human_id']}"

    added = await attach(client, url, png(), "menu bug.png")
    assert added.status_code == 201, added.text
    image = added.json()
    assert (image["media_type"], image["width"], image["height"]) == ("image/png", 3, 2)
    served = await client.get(f"/api/projects/{pid}/images/{image['id']}")
    assert served.content == png() and served.headers["content-type"] == "image/png"
    detail = (await client.get(url)).json()
    assert [i["filename"] for i in detail["images"]] == ["menu bug.png"]

    # The name and the claimed type are never trusted; only the bytes decide.
    fake = await attach(client, url, b"<script>alert(1)</script>", "evil.png")
    assert fake.status_code == 422 and "PNG, JPEG" in fake.text
    huge = await attach(client, url, png() + b"\x00" * (5 * 1024 * 1024))
    assert huge.status_code == 422 and "5 MB" in huge.text

    assert (await client.delete(f"/api/projects/{pid}/images/{image['id']}")).status_code == 204
    assert (await client.get(f"{url}/images")).json() == []


async def test_images_go_with_their_record(client: AsyncClient, tmp_path: Path) -> None:
    pid = await project(client, tmp_path)
    memory = (
        await client.post(f"/api/projects/{pid}/memory", json={"type": "bug", "title": "Glitch"})
    ).json()
    url = f"/api/projects/{pid}/memory/{memory['human_id']}"
    for _ in range(10):
        assert (await attach(client, url, png())).status_code == 201
    full = await attach(client, url, png())
    assert full.status_code == 422 and "10 images" in full.text
    assert len((await client.get(url)).json()["images"]) == 10
    image_id = (await client.get(f"{url}/images")).json()[0]["id"]

    assert (await client.delete(url)).status_code == 204
    assert (await client.get(f"/api/projects/{pid}/images/{image_id}")).status_code == 404


async def test_agents_see_attached_images(database_url: str, tmp_path: Path) -> None:
    async with app_client(database_url) as client:
        pid = await project(client, tmp_path)
        task = (await client.post(f"/api/projects/{pid}/tasks", json={"title": "Fix menu"})).json()
        await attach(client, f"/api/projects/{pid}/tasks/{task['human_id']}", png(), "menu.png")
        secret = (
            await client.post(
                f"/api/projects/{pid}/memory",
                json={"type": "note", "title": "Private", "ai_visibility": "hidden"},
            )
        ).json()
        await attach(client, f"/api/projects/{pid}/memory/{secret['human_id']}", png())

    async with agent(database_url) as session:
        ref = task["human_id"]
        failed, text = await call(session, "brain_context_pack", task=ref, project=pid)
        assert not failed and f"[1 image attached: brain_view_images {ref}]" in text
        failed, detail = await call(session, "brain_get_task", task=ref, project=pid)
        assert not failed and detail["images"][0]["filename"] == "menu.png"

        result = await session.call_tool("brain_view_images", {"record": ref, "project": pid})
        assert not result.is_error
        text_block, picture = result.content
        assert "menu.png" in text_block.text and "3x2" in text_block.text
        assert picture.type == "image" and picture.mime_type == "image/png"
        assert base64.b64decode(picture.data) == png()

        failed, text = await call(
            session, "brain_view_images", record=secret["human_id"], project=pid
        )
        assert failed and "hidden" in text
