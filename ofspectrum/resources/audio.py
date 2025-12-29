"""
Audio resource for watermark encoding and decoding
"""

from typing import Union, Optional, BinaryIO
from pathlib import Path
import httpx
from .base import BaseResource
from ..models.audio import EncodeResult, DecodeResult
from ..exceptions import raise_for_error, OfSpectrumError


class AudioResource(BaseResource):
    """Resource for audio watermark operations"""

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
        # Prepare form data (internal parameters are fixed, not user-configurable)
        form_data = {
            "token_id": token_id,
            "strength": str(strength),
            "smooth": str(smooth).lower(),
            "interval": "0.0",           # Fixed: no interval
            "save_file": "true",          # Fixed: always save to server
            "check_watermark": "true",    # Fixed: always check for existing watermark
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
        public_key: int = 258,
    ) -> DecodeResult:
        """
        Decode (detect) a watermark from an audio file.

        Args:
            audio: Audio file path or file-like object
            public_key: Public key for verification (default 258)

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
            "public_key": str(public_key),
            "save_file": "true",  # Fixed: always save usage
        }

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

    # Note: decode_from_url is not yet available
