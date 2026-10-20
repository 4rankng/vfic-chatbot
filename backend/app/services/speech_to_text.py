"""MiniMax speech-to-text for the Cloudfone call recordings.

The Cloudfone daily letter summarizes call recordings (``linkFile`` WAVs), but
the vendor rows carry no transcript text — the text must come from an ASR
provider. MiniMax ``POST /v1/speech_to_text`` (``asr-1.0``) is the engine:
accurate Vietnamese transcripts with 2-speaker diarization over the 8 kHz
telephony WAVs the vendor serves (verified live). The MiMo ASR endpoint was
tested and rejected: its language option is ``auto``/``zh``/``en`` only and
returns empty or garbage text for Vietnamese.

Contract with the caller (``app.services.cloudfone``): every failure — HTTP
error, timeout, unusable body — raises :class:`SpeechToTextError`, which the
caller treats as "no transcript for this call" and fail-softs around. The
vendor hard-rejects audio longer than 500 s with HTTP 400 and never truncates,
so recordings longer than ``chunk_seconds`` are split at PCM frame boundaries
(stdlib ``wave`` — the vendor serves PCM s16le WAV only) and transcribed chunk
by chunk, sequentially: daily volume is small and the tick carries its own
job-timeout budget.

The transport seam mirrors ``CloudfoneClient``: ``transport`` replaces the
HTTP call in tests (it receives each audio chunk as raw bytes); production
resolves the process-scoped httpx client through ``app.core.http``.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Awaitable, Callable

from app.core.config import MINIMAX_ASR_BASE

ASR_PATH = "/v1/speech_to_text"
ASR_MODEL = "asr-1.0"
ASR_RESPONSE_FORMAT = "verbose_json"
ASR_LANGUAGE = "vi"

AsrTransport = Callable[[bytes], Awaitable[dict]]


class SpeechToTextError(RuntimeError):
    """MiniMax rejected the transcription request or answered unusable data."""


class MiniMaxAsrClient:
    """MiniMax ``/v1/speech_to_text`` client (asr-1.0, verbose_json, Vietnamese).

    ``transcribe`` returns speaker-labeled text (``S1: …`` per line) rendered
    from the ``verbose_json`` segments, falling back to the plain ``text``
    field when the response carries no segments.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = MINIMAX_ASR_BASE,
        timeout: float = 120.0,
        chunk_seconds: int = 480,
        transport: AsrTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # 480 s keeps every chunk under the vendor's 500 s hard ceiling.
        self.chunk_seconds = chunk_seconds
        self._transport = transport

    async def transcribe(self, audio: bytes, *, filename: str = "recording.wav") -> str:
        """Speaker-labeled transcript of one recording.

        Audio longer than ``chunk_seconds`` is split at PCM frame boundaries
        and each chunk is transcribed sequentially; chunk texts join with a
        newline. Non-WAV bytes are never split (the vendor serves WAV only) —
        a >500 s non-WAV file reaches the API as-is and 400s into the same
        fail-soft path. Raises :class:`SpeechToTextError` on any failure.
        """
        texts: list[str] = []
        for chunk in _split_wav(audio, self.chunk_seconds):
            data = await self._post(chunk, filename)
            texts.append(_render_transcript(data))
        return "\n".join(texts)

    async def _post(self, audio: bytes, filename: str) -> dict:
        if self._transport is not None:
            data = await self._transport(audio)
        else:
            data = await self._post_http(audio, filename)
        if not isinstance(data, dict):
            raise SpeechToTextError("MiniMax trả dữ liệu không phải object")
        return data

    async def _post_http(self, audio: bytes, filename: str) -> dict:
        import httpx

        from app.core.http import get_http_client

        client = await get_http_client(
            "minimax_asr",
            base_url=self.base_url,
            timeout=self.timeout,
        )
        try:
            response = await client.post(
                ASR_PATH,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "language": ASR_LANGUAGE,
                },
                data={"model": ASR_MODEL, "response_format": ASR_RESPONSE_FORMAT},
                files={"file": (filename, audio, "audio/wav")},
            )
        except httpx.HTTPError as exc:
            raise SpeechToTextError(f"MiniMax không phản hồi: {exc}") from exc
        if response.status_code >= 400:
            raise SpeechToTextError(f"MiniMax trả lỗi HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise SpeechToTextError("MiniMax trả dữ liệu không phải JSON") from exc
        return data


def _render_transcript(data: dict) -> str:
    """Speaker-labeled text from a ``verbose_json`` envelope; ``text`` fallback."""
    segments = data.get("segments")
    if isinstance(segments, list) and segments:
        lines = [
            f"{segment.get('speaker', '')}: {segment.get('text', '')}"
            for segment in segments
            if isinstance(segment, dict)
        ]
        if lines:
            return "\n".join(lines)
    return str(data.get("text") or "")


def _is_wav(audio: bytes) -> bool:
    return audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"


def _split_wav(audio: bytes, chunk_seconds: int) -> list[bytes]:
    """PCM WAV audio cut into ``chunk_seconds`` pieces at frame boundaries.

    Non-WAV or unreadable bytes pass through whole: the vendor serves WAV
    only, so anything else is forwarded to the API as-is (a >500 s non-WAV
    file 400s there and the caller fail-softs).
    """
    if not _is_wav(audio):
        return [audio]
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            params = reader.getparams()
            frames_per_chunk = max(int(params.framerate * chunk_seconds), 1)
            if params.nframes <= frames_per_chunk:
                return [audio]
            chunks: list[bytes] = []
            while True:
                frames = reader.readframes(frames_per_chunk)
                if not frames:
                    break
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as writer:
                    writer.setparams(params)
                    writer.writeframes(frames)
                chunks.append(buffer.getvalue())
            return chunks or [audio]
    except (wave.Error, EOFError):
        return [audio]
