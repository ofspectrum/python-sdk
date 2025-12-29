"""
Notebooks resource for managing token notes
"""

from typing import List, Optional, Union, BinaryIO
from pathlib import Path
import mimetypes
from .base import BaseResource
from ..models.notebook import Notebook, NotebookCreateParams, NotebookUpdateParams
from ..exceptions import raise_for_error


class NotebooksResource(BaseResource):
    """Resource for managing watermark token notebooks (notes)"""

    def list(self, token_id: str) -> List[Notebook]:
        """
        List all notebooks for a specific token.

        Args:
            token_id: The token UUID

        Returns:
            List of Notebook objects

        Example:
            notebooks = client.notebooks.list(token_id="...")
            for nb in notebooks:
                print(f"{nb.note_name}: {nb.id}")
        """
        response = self._get(f"/watermark-notes?token_id={token_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns a direct list
        notes_data = data if isinstance(data, list) else data.get("data", {}).get("notes", [])
        return [Notebook.from_dict(n) for n in notes_data]

    def get(self, note_id: str) -> Notebook:
        """
        Get a specific notebook by ID.

        Args:
            note_id: The notebook UUID

        Returns:
            Notebook object

        Note:
            The backend doesn't have a single-note GET endpoint.
            This uses PATCH with empty body to get the note (returns current state).
        """
        # Use PATCH with empty body - backend returns the updated note
        response = self._patch(f"/watermark-notes/{note_id}", data={})
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns the note directly or wrapped in data
        note_data = data if isinstance(data, dict) and "id" in data else data.get("data", {})
        return Notebook.from_dict(note_data)

    def create(
        self,
        token_id: str,
        note_name: str,
        text_content: Optional[str] = None,
        is_public: bool = True,
        credential_val: Optional[str] = None,
    ) -> Notebook:
        """
        Create a new notebook for a token.

        Args:
            token_id: The token UUID to attach the notebook to
            note_name: Notebook name/title
            text_content: Notebook content (markdown supported)
            is_public: Whether the notebook is publicly visible (default: True)
            credential_val: Credential for private notes (default: "123" if not provided)

        Returns:
            Newly created Notebook object

        Example:
            notebook = client.notebooks.create(
                token_id="...",
                note_name="My Notes",
                text_content="Some content",
                is_public=True
            )
        """
        params = NotebookCreateParams(
            token_id=token_id,
            note_name=note_name,
            text_content=text_content,
            is_public=is_public,
            credential_val=credential_val,
        )

        response = self._post("/watermark-notes", data=params.to_dict())
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns the note directly
        note_data = data if isinstance(data, dict) and "id" in data else data.get("data", {})
        return Notebook.from_dict(note_data)

    def update(
        self,
        note_id: str,
        note_name: Optional[str] = None,
        text_content: Optional[str] = None,
        credential_val: Optional[str] = None,
    ) -> Notebook:
        """
        Update an existing notebook.

        Args:
            note_id: The notebook UUID
            note_name: New name/title (optional)
            text_content: New content (optional)
            credential_val: New password for private notes (optional)

        Returns:
            Updated Notebook object

        Note:
            is_public cannot be changed after creation.
        """
        params = NotebookUpdateParams(
            note_name=note_name,
            text_content=text_content,
            credential_val=credential_val,
        )

        update_data = params.to_dict()
        if not update_data:
            # Nothing to update, attempt to return current notebook
            return self.get(note_id)

        response = self._patch(f"/watermark-notes/{note_id}", data=update_data)
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns the note directly
        note_data = data if isinstance(data, dict) and "id" in data else data.get("data", {})
        return Notebook.from_dict(note_data)

    def delete(self, note_id: str) -> bool:
        """
        Delete a notebook.

        Args:
            note_id: The notebook UUID

        Returns:
            True if deleted successfully
        """
        response = self._delete(f"/watermark-notes/{note_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return True

    def list_media(self, note_id: str) -> List[dict]:
        """
        List all media files attached to a notebook.

        Args:
            note_id: The notebook UUID

        Returns:
            List of media dicts with id, filename, media_type, etc.
        """
        response = self._get(f"/watermark-notes/{note_id}/media")
        data = response.json()
        raise_for_error(data, response.status_code)

        return data if isinstance(data, list) else []

    def upload_media(
        self,
        note_id: str,
        file: Union[str, Path, BinaryIO],
        filename: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> dict:
        """
        Upload a media file to a notebook.

        Args:
            note_id: The notebook UUID
            file: File path or file-like object
            filename: Optional filename (required if file is a file-like object)
            media_type: Optional media type (auto-detected if not provided)

        Returns:
            Dict with upload result including media_id and url

        Example:
            result = client.notebooks.upload_media(
                note_id="...",
                file="path/to/audio.mp3"
            )
            print(f"Uploaded: {result['id']}")
        """
        if isinstance(file, (str, Path)):
            path = Path(file)
            actual_filename = path.name
            # Auto-detect media type from file extension
            if not media_type:
                mime_type, _ = mimetypes.guess_type(str(path))
                media_type = mime_type or "application/octet-stream"

            with open(path, "rb") as f:
                files = {"file": (actual_filename, f)}
                data = {"media_type": media_type}
                response = self._post(f"/watermark-notes/{note_id}/media", files=files, data=data)
        else:
            if not filename:
                raise ValueError("filename is required when uploading a file-like object")
            # Auto-detect media type from filename
            if not media_type:
                mime_type, _ = mimetypes.guess_type(filename)
                media_type = mime_type or "application/octet-stream"

            files = {"file": (filename, file)}
            data = {"media_type": media_type}
            response = self._post(f"/watermark-notes/{note_id}/media", files=files, data=data)

        resp_data = response.json()
        raise_for_error(resp_data, response.status_code)

        # Backend returns the media record directly
        return resp_data if isinstance(resp_data, dict) else resp_data.get("data", {})

    def delete_media(self, media_id: str) -> bool:
        """
        Delete a media file.

        Args:
            media_id: The media UUID

        Returns:
            True if deleted successfully

        Note:
            Unlike other methods, delete_media only needs the media_id,
            not the note_id.
        """
        response = self._delete(f"/watermark-notes/media/{media_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return True

    def get_media_url(self, media_id: str) -> str:
        """
        Get a signed URL for accessing a media file.

        Args:
            media_id: The media UUID

        Returns:
            Signed URL string

        Note:
            The signed URL may have an expiration time.
        """
        response = self._get(f"/watermark-notes/media/{media_id}/signed-url")
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns {"url": "..."} or {"data": {"url": "..."}}
        if isinstance(data, dict):
            return data.get("url", "") or data.get("data", {}).get("url", "")
        return ""

    def download_media(
        self,
        media_id: str,
        output_path: Optional[Union[str, Path]] = None,
    ) -> Union[bytes, str]:
        """
        Download a media file.

        Args:
            media_id: The media UUID
            output_path: Optional path to save the file. If provided,
                        saves to file and returns the path. If not,
                        returns the raw bytes.

        Returns:
            If output_path is provided: the output path as string
            Otherwise: the raw file bytes

        Example:
            # Download to file
            path = client.notebooks.download_media(
                media_id="...",
                output_path="downloaded.mp3"
            )

            # Download to memory
            content = client.notebooks.download_media(media_id="...")
        """
        response = self._get(f"/watermark-notes/media/{media_id}/download")

        if response.status_code != 200:
            try:
                data = response.json()
                raise_for_error(data, response.status_code)
            except Exception:
                from ..exceptions import OfSpectrumError
                raise OfSpectrumError(f"Download failed with status {response.status_code}")

        content = response.content

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return str(path)

        return content
