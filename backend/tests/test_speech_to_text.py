"""MiniMax speech-to-text client: multipart request shape, diarized rendering,
WAV chunking, and fail-loud error mapping.

The request-shape/error tests ride the default HTTP path against a registered
``httpx.MockTransport`` client (no sockets); the rendering/chunking tests
inject the bytes transport seam — same injection style as
``test_cloudfone_service.py``.
"""

# pyright: reportArgumentType=false

import io
import wave

import httpx
import pytest

from app.core.http import register_test_client
from app.services.speech_to_text import MiniMaxAsrClient, SpeechToTextError

VERBOSE_ENVELOPE = {
    "segments": [
        {"speaker": "S1", "text": "Alo ạ?"},
        {"speaker": "S2", "text": "Dạ em nghe ạ."},
    ],
    "text": "Alo ạ? Dạ em nghe ạ.",
}


def _wav(seconds: float, *, rate: int = 8000) -> bytes:
    """A silent PCM s16le mono WAV — the vendor recording shape (verified)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _mock_http(handler) -> None:
    """Register a MockTransport httpx client as the ``minimax_asr`` singleton."""
    register_test_client(
        "minimax_asr",
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.minimax.io",
        ),
    )


async def test_transcribe_sends_the_multipart_asr_request():
    """model/response_format ride the multipart body; language + Bearer the headers."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["headers"] = request.headers
        seen["content"] = request.content
        return httpx.Response(200, json=VERBOSE_ENVELOPE)

    _mock_http(handler)
    text = await MiniMaxAsrClient("asr-key").transcribe(_wav(2))

    assert seen["path"] == "/v1/speech_to_text"
    assert seen["headers"]["authorization"] == "Bearer asr-key"
    assert seen["headers"]["language"] == "vi"
    assert seen["headers"]["content-type"].startswith("multipart/form-data")
    body = seen["content"]
    assert b'name="model"' in body and b"asr-1.0" in body
    assert b'name="response_format"' in body and b"verbose_json" in body
    assert b'filename="recording.wav"' in body and b"audio/wav" in body
    assert text == "S1: Alo ạ?\nS2: Dạ em nghe ạ."


async def test_segments_render_speaker_labels():
    async def transport(_audio: bytes) -> dict:
        return VERBOSE_ENVELOPE

    text = await MiniMaxAsrClient("asr-key", transport=transport).transcribe(_wav(1))
    assert text == "S1: Alo ạ?\nS2: Dạ em nghe ạ."


async def test_empty_segments_fall_back_to_text():
    async def transport(_audio: bytes) -> dict:
        return {"segments": [], "text": "Nội dung cuộc gọi."}

    client = MiniMaxAsrClient("asr-key", transport=transport)
    assert await client.transcribe(_wav(1)) == "Nội dung cuộc gọi."

    async def transport_no_segments(_audio: bytes) -> dict:
        return {"text": "Không có trường segments."}

    client = MiniMaxAsrClient("asr-key", transport=transport_no_segments)
    assert await client.transcribe(_wav(1)) == "Không có trường segments."


async def test_long_wav_splits_into_sequential_chunks():
    """15 s at chunk_seconds=10 → 10 s + 5 s frames, never two calls in flight."""
    calls: list[bytes] = []
    in_flight = 0

    async def transport(audio: bytes) -> dict:
        nonlocal in_flight
        in_flight += 1
        assert in_flight == 1, "chunks must transcribe sequentially"
        calls.append(audio)
        reply = {"text": f"phần {len(calls)}"}
        in_flight -= 1
        return reply

    client = MiniMaxAsrClient("asr-key", chunk_seconds=10, transport=transport)
    text = await client.transcribe(_wav(15))

    assert text == "phần 1\nphần 2"
    assert len(calls) == 2
    frames = []
    for chunk in calls:
        with wave.open(io.BytesIO(chunk)) as reader:
            frames.append(reader.getnframes())
    # 8000 Hz × 10 s frames first, the 5 s remainder second — frame-aligned splits.
    assert frames == [80_000, 40_000]


async def test_short_wav_is_sent_as_one_request():
    calls: list[bytes] = []

    async def transport(audio: bytes) -> dict:
        calls.append(audio)
        return {"text": "nguyên bản"}

    client = MiniMaxAsrClient("asr-key", chunk_seconds=10, transport=transport)
    assert await client.transcribe(_wav(9)) == "nguyên bản"
    assert len(calls) == 1


async def test_http_400_and_non_json_raise():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"base_resp": {"status_code": 2048}})

    _mock_http(handler)
    with pytest.raises(SpeechToTextError, match="400"):
        await MiniMaxAsrClient("asr-key").transcribe(_wav(1))

    def handler_html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    _mock_http(handler_html)
    with pytest.raises(SpeechToTextError, match="không phải JSON"):
        await MiniMaxAsrClient("asr-key").transcribe(_wav(1))


async def test_network_errors_wrap_into_speech_to_text_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _mock_http(handler)
    with pytest.raises(SpeechToTextError, match="không phản hồi"):
        await MiniMaxAsrClient("asr-key").transcribe(_wav(1))


async def test_non_dict_envelope_raises():
    async def transport(_audio: bytes) -> dict:
        return ["not", "a", "dict"]

    with pytest.raises(SpeechToTextError, match="không phải object"):
        await MiniMaxAsrClient("asr-key", transport=transport).transcribe(_wav(1))
