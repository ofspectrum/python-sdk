"""
Audio resource for watermark encoding and decoding
"""

from typing import Any, Iterable, Union, Optional, BinaryIO
from pathlib import Path
import json
from urllib.parse import urlsplit, urlunsplit
import httpx
from .base import BaseResource
from ..models.audio import DecodeResult, EncodeResult, StreamingEncodeResult
from ..exceptions import raise_for_error, OfSpectrumError


class AudioResource(BaseResource):
    """Resource for audio watermark operations"""

    def _websocket_url(self, path: str) -> str:
        base = self._client._base_url.rstrip("/")
        split = urlsplit(base)
        scheme = "wss" if split.scheme == "https" else "ws"
        ws_path = f"{split.path.rstrip('/')}/{path.lstrip('/')}"
        return urlunsplit((scheme, split.netloc, ws_path, "", ""))

    def encode(
        self,
        audio: Union[str, Path, BinaryIO],
        token_id: str,
        *,
        strength: float = 1.0,
        smooth: bool = True,
        output_path: Optional[Union[str, Path]] = None,
    ) -> EncodeResult:
        """
        Encode a watermark into an audio file.

        Args:
            audio: Audio file path or file-like object
            token_id: Watermark token ID to use
            strength: Watermark strength (0.1-2.0, default 1.0)
            smooth: Smooth audio to reduce artifacts (default True)
            output_path: Optional path to save the watermarked audio

        Returns:
            EncodeResult with audio data or download URL

        Example:
            result = client.audio.encode(
                audio="input.mp3",
                token_id="uuid-here",
                output_path="watermarked.mp3"
            )
            print(f"Encoded {result.audio_duration}s of audio")
        """
        # Prepare form data for the product API.
        form_data = {
            "token_id": token_id,
            "strength": str(strength),
            "smooth": str(smooth).lower(),
            "save_file": "true",
            "check_watermark": "true",
            "response_format": "json" if output_path else "stream",
        }

        # Open file if path provided
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            with open(path, "rb") as f:
                files = {"audio": (path.name, f)}
                response = self._post(
                    "/audio/watermark/encode",
                    data=form_data,
                    files=files,
                    timeout=180.0,  # Audio processing can take time
                )
        else:
            # File-like object
            filename = getattr(audio, "name", "audio.wav")
            if hasattr(audio, "seek"):
                audio.seek(0)
            files = {"audio": (filename, audio)}
            response = self._post(
                "/audio/watermark/encode",
                data=form_data,
                files=files,
                timeout=180.0,
            )

        # Handle JSON response mode
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
            raise_for_error(data, response.status_code)

            result = EncodeResult.from_dict(data.get("data", {}))

            # Download and save if output_path provided
            if output_path and result.download_url:
                result.save(str(output_path))

            return result

        # Handle stream response mode
        if response.status_code != 200:
            # Try to parse as JSON error
            try:
                data = response.json()
                raise_for_error(data, response.status_code)
            except Exception:
                raise OfSpectrumError(
                    message=f"Encoding failed with status {response.status_code}",
                    status_code=response.status_code,
                )

        audio_bytes = response.content
        duration = int(response.headers.get("X-Audio-Duration", 0))
        returned_token_id = response.headers.get("X-Token-Id", token_id)
        content_disp = response.headers.get("Content-Disposition", "")

        # Extract filename from content-disposition
        file_name = "watermarked.wav"
        if "filename*=" in content_disp:
            # UTF-8 encoded filename
            import urllib.parse
            parts = content_disp.split("filename*=UTF-8''")
            if len(parts) > 1:
                file_name = urllib.parse.unquote(parts[1].strip())
        elif "filename=" in content_disp:
            parts = content_disp.split("filename=")
            if len(parts) > 1:
                file_name = parts[1].strip().strip('"')

        result = EncodeResult.from_bytes(
            audio_bytes=audio_bytes,
            audio_duration=duration,
            token_id=returned_token_id,
            file_name=file_name,
            content_type=content_type,
        )

        # Save if output_path provided
        if output_path:
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

        return result

    def decode(
        self,
        audio: Union[str, Path, BinaryIO],
        *,
        public_key: Optional[int] = None,
    ) -> DecodeResult:
        """
        Decode (detect) a watermark from an audio file.

        Args:
            audio: Audio file path or file-like object
            public_key: Optional verification key when your workflow requires one

        Returns:
            DecodeResult with watermark information

        Example:
            result = client.audio.decode("suspect.mp3")
            if result.watermarked:
                print(f"Found watermark! Token: {result.token_id}")
            else:
                print("No watermark detected")
        """
        # Internal parameters are fixed, not user-configurable
        form_data = {
            "save_file": "true",  # Fixed: always save usage
        }
        if public_key is not None:
            form_data["public_key"] = str(public_key)

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            with open(path, "rb") as f:
                files = {"audio": (path.name, f)}
                response = self._post(
                    "/audio/watermark/decode",
                    data=form_data,
                    files=files,
                    timeout=180.0,
                )
        else:
            filename = getattr(audio, "name", "audio.wav")
            if hasattr(audio, "seek"):
                audio.seek(0)
            files = {"audio": (filename, audio)}
            response = self._post(
                "/audio/watermark/decode",
                data=form_data,
                files=files,
                timeout=180.0,
            )

        data = response.json()
        raise_for_error(data, response.status_code)

        return DecodeResult.from_dict(data.get("data", {}))

    def stream_encode_pcm(
        self,
        pcm_chunks: Iterable[bytes],
        token_id: str,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
        strength: float = 1.0,
        smooth: bool = True,
    ) -> StreamingEncodeResult:
        """
        Stream raw PCM float32 little-endian audio to Neo for watermark encoding.

        The SDK sends token_id and product-level encoding settings to Neo.
        Returned bytes are encoded raw PCM float32 little-endian, not WAV.
        """
        if not token_id:
            raise ValueError("token_id is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")

        try:
            from websockets.sync.client import connect
        except Exception as exc:
            raise OfSpectrumError(
                message="Streaming encode requires the 'websockets' package",
                code="MissingDependency",
            ) from exc

        url = self._websocket_url("/audio/watermark/ws/encode")
        headers = {"Authorization": f"Bearer {self._client._api_key}"}
        config = {
            "type": "config",
            "config": {
                "token_id": token_id,
                "sample_rate": sample_rate,
                "channels": channels,
                "strength": strength,
                "smooth": smooth,
            },
        }
        encoded_chunks = []
        events = []

        try:
            ws_context = connect(url, additional_headers=headers, open_timeout=self._client._timeout)
        except TypeError:
            ws_context = connect(url, extra_headers=headers, open_timeout=self._client._timeout)

        with ws_context as ws:
            ws.send(json.dumps(config))
            for chunk in pcm_chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError("pcm_chunks must yield bytes-like objects")
                if len(chunk) == 0:
                    continue
                ws.send(bytes(chunk))
                while True:
                    try:
                        message = ws.recv(timeout=0.01)
                    except TimeoutError:
                        break
                    self._collect_stream_encode_message(message, encoded_chunks, events)
            ws.send(json.dumps({"type": "end"}))
            while True:
                try:
                    message = ws.recv()
                except Exception:
                    break
                if self._collect_stream_encode_message(message, encoded_chunks, events):
                    break

        return StreamingEncodeResult(
            encoded_pcm=b"".join(encoded_chunks),
            token_id=token_id,
            sample_rate=sample_rate,
            channels=channels,
            events=events,
        )

    @staticmethod
    def _collect_stream_encode_message(
        message: Any,
        encoded_chunks: list,
        events: list,
    ) -> bool:
        if isinstance(message, bytes):
            encoded_chunks.append(message)
            return False
        if isinstance(message, str):
            try:
                event = json.loads(message)
            except Exception:
                event = {"type": "message", "message": message}
            if isinstance(event, dict):
                events.append(event)
                if event.get("type") in {"error", "quota_exceeded"}:
                    raise OfSpectrumError(
                        message=str(event.get("message") or "Streaming encode failed"),
                        code=str(event.get("type") or "StreamingEncodeError"),
                    )
                return event.get("type") == "done"
        return False

    # Note: decode_from_url is not yet available
