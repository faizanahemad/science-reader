"""Audio transcription utilities shared across server endpoints."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import IO, List, Optional, Tuple, TYPE_CHECKING, Union

from common import USE_OPENAI_API

if TYPE_CHECKING:  # pragma: no cover
    from werkzeug.datastructures import FileStorage

AudioSource = Union[str, os.PathLike[str], IO[bytes], "FileStorage"]

SENTENCE_ENDINGS = (".", "!", "?")
CONVERT_TO_MP3_EXTENSIONS = {".mp4", ".m4a", ".ogg", ".oga", ".webm"}


def transcribe_audio(
    audio_source: AudioSource,
    use_openai: Optional[bool] = None,
    openai_api_key: Optional[str] = None,
    assemblyai_api_key: Optional[str] = None,
    paragraph_gap_seconds: float = 2.0,
) -> str:
    """Transcribe the provided audio input and return plain-text paragraphs.

    Args:
        audio_source: Either a path to a local audio file or a file-like object
            such as the `FileStorage` object returned by Flask's
            `request.files`.
        use_openai: Flag to force OpenAI transcription. Defaults to the global
            configuration (`USE_OPENAI_API`) when not supplied.
        openai_api_key: Optional override for the OpenAI API key. When omitted,
            the function looks for `openAIKey` in the environment.
        assemblyai_api_key: Optional override for the AssemblyAI API key. When
            omitted, the function looks for `ASSEMBLYAI_API_KEY` in the
            environment.
        paragraph_gap_seconds: Minimum time gap that triggers a paragraph break
            when parsing SRT responses from OpenAI.

    Returns:
        A string containing the final transcription with paragraph breaks.

    Raises:
        FileNotFoundError: If the supplied file path does not exist.
        ValueError: If the input type is not supported.
        RuntimeError: When an external transcription provider returns an error.
    """
    use_openai = USE_OPENAI_API if use_openai is None else use_openai
    audio_path, should_cleanup = _normalize_audio_input(audio_source)
    prepared_audio_path, conversion_cleanup = _prepare_audio_for_transcription(audio_path)

    try:
        if use_openai:
            return _transcribe_with_openai(
                prepared_audio_path,
                openai_api_key=openai_api_key,
                paragraph_gap_seconds=paragraph_gap_seconds,
            )
        return _transcribe_with_assemblyai(
            prepared_audio_path,
            assemblyai_api_key=assemblyai_api_key,
        )
    finally:
        if conversion_cleanup and os.path.exists(prepared_audio_path):
            os.unlink(prepared_audio_path)
        if should_cleanup and os.path.exists(audio_path):
            os.unlink(audio_path)


def _normalize_audio_input(audio_source: AudioSource) -> Tuple[str, bool]:
    """Persist the audio input to disk if needed and return a usable path.

    Args:
        audio_source: Input argument provided to `transcribe_audio`.

    Returns:
        A tuple containing the path to the audio file and a boolean that
        indicates whether the caller should delete the file after use.
    """
    if isinstance(audio_source, (str, os.PathLike)):
        path = os.fspath(audio_source)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Audio file does not exist: {path}")
        return path, False

    filename = getattr(audio_source, "filename", None) or getattr(
        audio_source, "name", ""
    )
    suffix = Path(filename).suffix or ".tmp"
    temp_file_path = _create_temp_file_path(suffix)

    if hasattr(audio_source, "save"):
        audio_source.save(temp_file_path)
        return temp_file_path, True

    if hasattr(audio_source, "read"):
        data = audio_source.read()
        if isinstance(data, str):
            data = data.encode("utf-8")

        with open(temp_file_path, "wb") as temp_file:
            temp_file.write(data)

        if hasattr(audio_source, "seek"):
            audio_source.seek(0)

        return temp_file_path, True

    raise ValueError("Unsupported audio input. Expected path or file-like object.")


def _prepare_audio_for_transcription(audio_path: str) -> Tuple[str, bool]:
    """Convert unsupported formats (e.g., mp4/ogg) to MP3 for transcription APIs."""
    extension = Path(audio_path).suffix.lower()
    if extension in (".mp3",):
        return audio_path, False

    if extension in CONVERT_TO_MP3_EXTENSIONS:
        return _convert_to_mp3(audio_path)

    return audio_path, False


def _convert_to_mp3(audio_path: str) -> Tuple[str, bool]:
    """Convert the provided audio file to MP3 using ffmpeg."""
    mp3_path = _create_temp_file_path(".mp3")
    ffmpeg_binary = os.environ.get("FFMPEG_BIN", "ffmpeg")
    command = [
        ffmpeg_binary,
        "-y",
        "-i",
        audio_path,
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ar",
        "44100",
        "-ac",
        "2",
        mp3_path,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg binary not found. Install ffmpeg or set the FFMPEG_BIN environment variable."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr_output = exc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg failed to convert audio: {stderr_output}") from exc

    return mp3_path, True


def _create_temp_file_path(suffix: str) -> str:
    """Create a temporary file and return its path."""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file_path = temp_file.name
    temp_file.close()
    return temp_file_path


def _transcribe_with_openai(
    file_path: str,
    openai_api_key: Optional[str],
    paragraph_gap_seconds: float,
) -> str:
    """Transcribe audio using OpenAI Whisper and format paragraphs via SRT gaps."""
    from openai import OpenAI  # Imported lazily to keep optional dependency optional

    api_key = openai_api_key or os.environ.get("openAIKey")
    if not api_key:
        raise RuntimeError("OpenAI API key is missing. Set the openAIKey environment variable.")

    client = OpenAI(api_key=api_key)
    with open(file_path, "rb") as audio_file:
        srt_response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="srt",
            language="en",
        )

    paragraphs = _srt_to_paragraphs(str(srt_response), paragraph_gap_seconds)
    return paragraphs or str(srt_response).strip()


def _transcribe_with_assemblyai(
    file_path: str,
    assemblyai_api_key: Optional[str],
) -> str:
    """Transcribe audio using AssemblyAI."""
    import assemblyai as aai  # Imported lazily to keep optional dependency optional

    api_key = assemblyai_api_key or os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "AssemblyAI API key is missing. Set the ASSEMBLYAI_API_KEY environment variable."
        )

    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(file_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"Transcription failed: {transcript.error}")

    return (transcript.text or "").strip()


def _srt_to_paragraphs(srt_text: str, paragraph_gap_seconds: float) -> str:
    """Convert SRT output to readable paragraphs using timing metadata."""
    segments = _parse_srt_segments(srt_text)
    if not segments:
        return srt_text.strip()

    paragraphs: List[str] = []
    current_segment: List[str] = []
    last_end = segments[0]["start"]

    for segment in segments:
        if current_segment:
            gap = segment["start"] - last_end
            previous_text = current_segment[-1]
            if gap > paragraph_gap_seconds and _ends_sentence(previous_text):
                paragraphs.append(" ".join(current_segment).strip())
                current_segment = []

        current_segment.append(segment["text"].strip())
        last_end = segment["end"]

    if current_segment:
        paragraphs.append(" ".join(current_segment).strip())

    return "\n\n".join(paragraphs).strip()


def _parse_srt_segments(srt_text: str) -> List[dict]:
    """Parse SRT text into a list of timed segments."""
    segments: List[dict] = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        timing_line_index = 0
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            timing_line_index = 1

        if "-->" not in lines[timing_line_index]:
            continue

        try:
            start_text, end_text = [
                part.strip() for part in lines[timing_line_index].split("-->")
            ]
            text_lines = lines[timing_line_index + 1 :]
            if not text_lines:
                continue

            segments.append(
                {
                    "start": _timestamp_to_seconds(start_text),
                    "end": _timestamp_to_seconds(end_text),
                    "text": " ".join(text_lines),
                }
            )
        except ValueError:
            continue

    return segments


def _timestamp_to_seconds(timestamp: str) -> float:
    """Convert an SRT timestamp (HH:MM:SS,mmm) to seconds."""
    hours, minutes, rest = timestamp.split(":")
    seconds, milliseconds = rest.split(",")
    total_seconds = (
        int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000.0
    )
    return total_seconds


def _ends_sentence(text: str) -> bool:
    """Return True when the provided text looks like it ends a sentence."""
    text = text.rstrip()
    return text.endswith(SENTENCE_ENDINGS)


__all__ = ["transcribe_audio"]

