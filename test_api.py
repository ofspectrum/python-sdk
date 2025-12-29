"""
Complete API Test Script
Tests both SDK and direct URL (curl-style) calls

Usage:
    # Set environment variables first
    export TEST_API_KEY_USER_A="your_api_key"
    export TEST_API_KEY_USER_B="another_api_key"
    export TEST_API_BASE_URL="http://localhost:8000/api/v1"  # optional

    # Run test
    python test_api.py
"""

import os
import sys
import subprocess
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

# =============================================================================
# Auto-install dependencies
# =============================================================================

def check_and_install_deps():
    """Check and install required dependencies"""
    required = ['requests']
    missing = []

    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[Setup] Installing missing dependencies: {missing}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  Dependencies installed")

    # Check if SDK is installed or available locally
    sdk_path = Path(__file__).parent
    if (sdk_path / 'ofspectrum').exists():
        # Local SDK available
        sys.path.insert(0, str(sdk_path))
    else:
        # Try to install from PyPI
        try:
            import ofspectrum
        except ImportError:
            print("[Setup] Installing ofspectrum SDK...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'ofspectrum'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  SDK installed")

check_and_install_deps()

import json
import traceback
import requests
import wave
import struct

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import OfSpectrumError, AuthenticationError, ValidationError

# =============================================================================
# Configuration
# =============================================================================

# Load from environment variables
API_KEY_USER_A = os.environ.get("TEST_API_KEY_USER_A", "")
API_KEY_USER_B = os.environ.get("TEST_API_KEY_USER_B", "")
BASE_URL = os.environ.get("TEST_API_BASE_URL", "http://localhost:8000/api/v1")

if not API_KEY_USER_A or not API_KEY_USER_B:
    print("Please set environment variables:")
    print("  TEST_API_KEY_USER_A=<your_api_key>")
    print("  TEST_API_KEY_USER_B=<another_api_key>")
    print("  TEST_API_BASE_URL=<optional, defaults to localhost:8000>")
    sys.exit(1)

# Test results tracking
results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def log_pass(test_name, msg=""):
    print(f"  ✅ {test_name}" + (f": {msg}" if msg else ""))
    results["passed"].append(test_name)

def log_fail(test_name, msg=""):
    print(f"  ❌ {test_name}" + (f": {msg}" if msg else ""))
    results["failed"].append((test_name, msg))

def log_warn(test_name, msg=""):
    print(f"  ⚠️  {test_name}" + (f": {msg}" if msg else ""))
    results["warnings"].append((test_name, msg))

def create_test_audio(path: str):
    """Create a simple test WAV file"""
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        # Create 2 seconds of audio
        for i in range(88200):
            value = int(10000 * (i / 88200))
            w.writeframes(struct.pack('<h', value))
    return path

# =============================================================================
# PART 1: Direct URL (curl-style) Tests
# =============================================================================

def test_url_tokens_list(api_key):
    """Test GET /tokens/ via direct URL"""
    print("\n--- [URL] Testing GET /tokens/ ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(f"{BASE_URL}/tokens/", headers=headers)

        if response.status_code == 200:
            data = response.json()
            log_pass("[URL] GET /tokens/", f"Status: {response.status_code}, Count: {len(data)}")
            return data
        else:
            log_fail("[URL] GET /tokens/", f"Status: {response.status_code}, Body: {response.text[:100]}")
            return None
    except Exception as e:
        log_fail("[URL] GET /tokens/", str(e))
        return None

def test_url_quotas_all(api_key):
    """Test GET /usage/quotas/all via direct URL"""
    print("\n--- [URL] Testing GET /usage/quotas/all ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(f"{BASE_URL}/usage/quotas/all", headers=headers)

        if response.status_code == 200:
            data = response.json()
            log_pass("[URL] GET /usage/quotas/all", f"Status: {response.status_code}, Count: {len(data)}")
            # Verify only 5 quotas returned
            if len(data) == 5:
                log_pass("[URL] Quotas filter", "Exactly 5 quotas returned")
            else:
                log_warn("[URL] Quotas filter", f"Expected 5, got {len(data)}")
            # Print quota names
            for q in data:
                print(f"    - {q.get('service_name')}: {q.get('remaining')}/{q.get('quota_limit')}")
            return data
        else:
            log_fail("[URL] GET /usage/quotas/all", f"Status: {response.status_code}")
            return None
    except Exception as e:
        log_fail("[URL] GET /usage/quotas/all", str(e))
        return None

def test_url_encode(api_key, token_id, audio_path, output_path):
    """Test POST /audio/watermark/encode via direct URL (stream response)"""
    print("\n--- [URL] Testing POST /audio/watermark/encode ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(audio_path, 'rb') as f:
            files = {'audio': ('test.wav', f, 'audio/wav')}
            data = {
                'token_id': token_id,
                'strength': '1.0',
                'normalize': 'true',
                'response_type': 'stream'
            }
            response = requests.post(
                f"{BASE_URL}/audio/watermark/encode",
                headers=headers,
                files=files,
                data=data
            )

        if response.status_code == 200:
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'audio' in content_type or 'octet-stream' in content_type:
                # Save the audio file
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                log_pass("[URL] POST encode (stream)", f"Saved {len(response.content)} bytes")

                # Check response headers for metadata
                duration = response.headers.get('X-Audio-Duration')
                result_token = response.headers.get('X-Token-Id')
                print(f"    X-Audio-Duration: {duration}")
                print(f"    X-Token-Id: {result_token}")

                # Verify no encoding_info in headers
                if 'X-Encoding-Info' in response.headers:
                    log_warn("[URL] encode headers", "X-Encoding-Info exposed")
                else:
                    log_pass("[URL] encode security", "No encoding_info in headers")

                return output_path
            else:
                log_fail("[URL] POST encode", f"Unexpected content type: {content_type}")
                return None
        else:
            log_fail("[URL] POST encode", f"Status: {response.status_code}, Body: {response.text[:200]}")
            return None
    except Exception as e:
        log_fail("[URL] POST encode", str(e))
        traceback.print_exc()
        return None

def test_url_decode(api_key, audio_path):
    """Test POST /audio/watermark/decode via direct URL"""
    print("\n--- [URL] Testing POST /audio/watermark/decode ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(audio_path, 'rb') as f:
            files = {'audio': ('watermarked.wav', f, 'audio/wav')}
            response = requests.post(
                f"{BASE_URL}/audio/watermark/decode",
                headers=headers,
                files=files
            )

        if response.status_code == 200:
            data = response.json()
            log_pass("[URL] POST decode", f"Status: 200")

            # Check response fields
            if 'data' in data:
                result = data['data']
            else:
                result = data

            watermarked = result.get('watermarked')
            token_id = result.get('token_id')
            print(f"    watermarked: {watermarked}")
            print(f"    token_id: {token_id}")

            # Verify simplified response (no encoding_info)
            if 'encoding_info' in result:
                log_warn("[URL] decode security", "encoding_info exposed")
            else:
                log_pass("[URL] decode security", "No encoding_info in response")

            return result
        else:
            log_fail("[URL] POST decode", f"Status: {response.status_code}, Body: {response.text[:200]}")
            return None
    except Exception as e:
        log_fail("[URL] POST decode", str(e))
        traceback.print_exc()
        return None

def test_url_notebooks_list(api_key, token_id):
    """Test GET /watermark-notes via direct URL"""
    print("\n--- [URL] Testing GET /watermark-notes ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(
            f"{BASE_URL}/watermark-notes?token_id={token_id}",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            log_pass("[URL] GET /watermark-notes", f"Status: 200, Count: {len(data)}")
            return data
        else:
            log_fail("[URL] GET /watermark-notes", f"Status: {response.status_code}")
            return None
    except Exception as e:
        log_fail("[URL] GET /watermark-notes", str(e))
        return None

def test_url_notebooks_media_list(api_key, note_id):
    """Test GET /watermark-notes/{note_id}/media via direct URL"""
    print("\n--- [URL] Testing GET /watermark-notes/{note_id}/media ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(
            f"{BASE_URL}/watermark-notes/{note_id}/media",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            log_pass("[URL] GET media list", f"Status: 200, Count: {len(data)}")

            # Verify no media_url exposed
            for m in data:
                if 'media_url' in m:
                    log_warn("[URL] media list security", "media_url exposed")
                    break
            else:
                log_pass("[URL] media list security", "No media_url in response")

            return data
        else:
            log_fail("[URL] GET media list", f"Status: {response.status_code}")
            return None
    except Exception as e:
        log_fail("[URL] GET media list", str(e))
        return None

def test_url_media_upload(api_key, note_id, file_path):
    """Test POST /watermark-notes/{note_id}/media via direct URL"""
    print("\n--- [URL] Testing POST /watermark-notes/{note_id}/media ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(file_path, 'rb') as f:
            files = {'file': ('test.wav', f, 'audio/wav')}
            data = {'media_type': 'audio/wav'}
            response = requests.post(
                f"{BASE_URL}/watermark-notes/{note_id}/media",
                headers=headers,
                files=files,
                data=data
            )

        if response.status_code == 200:
            result = response.json()
            log_pass("[URL] POST media upload", f"Media ID: {result.get('id', 'N/A')[:8]}...")

            # Verify no media_url exposed
            if 'media_url' in result:
                log_warn("[URL] upload security", "media_url exposed")
            else:
                log_pass("[URL] upload security", "No media_url in response")

            return result
        else:
            log_fail("[URL] POST media upload", f"Status: {response.status_code}, Body: {response.text[:200]}")
            return None
    except Exception as e:
        log_fail("[URL] POST media upload", str(e))
        return None

def test_url_media_signed_url(api_key, media_id):
    """Test GET /watermark-notes/media/{media_id}/signed-url via direct URL"""
    print("\n--- [URL] Testing GET media signed-url ---")
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(
            f"{BASE_URL}/watermark-notes/media/{media_id}/signed-url",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            url = data.get('url', '')

            # Verify it's a download token URL, not direct storage
            if '/download?token=' in url:
                log_pass("[URL] signed-url format", "Returns download token URL")
            elif 'supabase' in url.lower() or 'storage' in url.lower():
                log_warn("[URL] signed-url security", f"Exposes storage URL: {url[:50]}...")
            else:
                log_pass("[URL] GET signed-url", f"URL: {url[:50]}...")

            return url
        else:
            log_fail("[URL] GET signed-url", f"Status: {response.status_code}")
            return None
    except Exception as e:
        log_fail("[URL] GET signed-url", str(e))
        return None

def test_url_invalid_api_key():
    """Test authentication with invalid API key"""
    print("\n--- [URL] Testing Invalid API Key ---")
    try:
        headers = {"Authorization": "Bearer invalid_key_12345"}
        response = requests.get(f"{BASE_URL}/tokens/", headers=headers)

        if response.status_code == 401:
            log_pass("[URL] Invalid API key", "Correctly returns 401")
        else:
            log_fail("[URL] Invalid API key", f"Expected 401, got {response.status_code}")
    except Exception as e:
        log_fail("[URL] Invalid API key", str(e))

def test_url_cross_user_access(api_key_b, note_id_a):
    """Test User B trying to access User A's resources"""
    print("\n--- [URL] Testing Cross-User Access Control ---")

    headers = {"Authorization": f"Bearer {api_key_b}"}

    # Try to delete User A's notebook
    response = requests.delete(
        f"{BASE_URL}/watermark-notes/{note_id_a}",
        headers=headers
    )

    if response.status_code == 403:
        log_pass("[URL] Cross-user delete", "Correctly blocked with 403")
    elif response.status_code == 404:
        log_pass("[URL] Cross-user delete", "Correctly blocked (404)")
    else:
        log_fail("[URL] Cross-user delete", f"Expected 403/404, got {response.status_code}")

# =============================================================================
# PART 2: SDK Tests
# =============================================================================

def test_sdk_tokens(client):
    """Test token listing via SDK"""
    print("\n--- [SDK] Testing tokens.list() ---")
    try:
        tokens = client.tokens.list()
        if tokens:
            log_pass("[SDK] tokens.list()", f"Found {len(tokens)} tokens")
            return tokens[0]
        else:
            log_warn("[SDK] tokens.list()", "No tokens found")
            return None
    except Exception as e:
        log_fail("[SDK] tokens.list()", str(e))
        return None

def test_sdk_quotas(client):
    """Test quota methods via SDK"""
    print("\n--- [SDK] Testing Quotas ---")
    try:
        # Get encode quota
        quota = client.quotas.get_encode_quota()
        log_pass("[SDK] quotas.get_encode_quota()", f"Remaining: {quota.remaining}/{quota.quota_limit}")
    except Exception as e:
        log_fail("[SDK] quotas.get_encode_quota()", str(e))

    try:
        # Get all quotas
        all_quotas = client.quotas.get_all()
        log_pass("[SDK] quotas.get_all()", f"Count: {len(all_quotas)}")

        # Verify 5 quotas
        if len(all_quotas) == 5:
            log_pass("[SDK] Quotas filter", "Exactly 5 quotas returned")
        else:
            log_warn("[SDK] Quotas filter", f"Expected 5, got {len(all_quotas)}")
    except Exception as e:
        log_fail("[SDK] quotas.get_all()", str(e))

def test_sdk_encode(client, token_id, audio_path, output_path):
    """Test encode via SDK"""
    print("\n--- [SDK] Testing audio.encode() ---")
    try:
        result = client.audio.encode(
            audio=audio_path,
            token_id=token_id,
            strength=1.0,
            output_path=output_path
        )
        if result.audio_duration > 0:
            log_pass("[SDK] audio.encode()", f"Duration: {result.audio_duration}s")

            # Verify no encoding_info
            if hasattr(result, 'encoding_info') and result.encoding_info:
                log_warn("[SDK] encode security", "encoding_info exists")
            else:
                log_pass("[SDK] encode security", "No encoding_info")

            return output_path
        else:
            log_fail("[SDK] audio.encode()", "Duration is 0")
            return None
    except Exception as e:
        log_fail("[SDK] audio.encode()", str(e))
        traceback.print_exc()
        return None

def test_sdk_decode(client, audio_path):
    """Test decode via SDK"""
    print("\n--- [SDK] Testing audio.decode() ---")
    try:
        result = client.audio.decode(audio=audio_path)
        log_pass("[SDK] audio.decode()", f"watermarked={result.watermarked}, token_id={result.token_id}")

        # Verify no encoding_info
        if hasattr(result, 'encoding_info') and result.encoding_info:
            log_warn("[SDK] decode security", "encoding_info exists")
        else:
            log_pass("[SDK] decode security", "No encoding_info")

        return result
    except Exception as e:
        log_fail("[SDK] audio.decode()", str(e))
        return None

def test_sdk_notebooks(client, token_id, audio_path):
    """Test notebooks methods via SDK"""
    print("\n--- [SDK] Testing Notebooks ---")

    # List notebooks
    try:
        notebooks = client.notebooks.list(token_id=token_id)
        log_pass("[SDK] notebooks.list()", f"Found {len(notebooks)} notebooks")
    except Exception as e:
        log_fail("[SDK] notebooks.list()", str(e))
        return

    # Find a notebook with media for testing
    test_notebook = None
    for nb in notebooks:
        test_notebook = nb
        break

    if not test_notebook:
        log_warn("[SDK] notebooks", "No notebooks to test")
        return

    # List media
    try:
        media_list = client.notebooks.list_media(note_id=test_notebook.id)
        log_pass("[SDK] notebooks.list_media()", f"Found {len(media_list)} media files")

        # Verify no media_url
        for m in media_list:
            if 'media_url' in m:
                log_warn("[SDK] list_media security", "media_url exposed")
                break
        else:
            log_pass("[SDK] list_media security", "No media_url")
    except Exception as e:
        log_fail("[SDK] notebooks.list_media()", str(e))

def test_sdk_strength_validation(client, token_id, audio_path):
    """Test strength parameter validation via SDK"""
    print("\n--- [SDK] Testing Strength Validation ---")

    # Too low
    try:
        client.audio.encode(audio=audio_path, token_id=token_id, strength=0.05)
        log_fail("[SDK] strength=0.05", "Should have been rejected")
    except (ValidationError, OfSpectrumError) as e:
        if "strength" in str(e).lower() or "0.1" in str(e):
            log_pass("[SDK] strength=0.05", "Correctly rejected")
        else:
            log_warn("[SDK] strength=0.05", f"Rejected: {e}")
    except Exception as e:
        log_warn("[SDK] strength=0.05", f"Error: {e}")

    # Too high
    try:
        client.audio.encode(audio=audio_path, token_id=token_id, strength=2.5)
        log_fail("[SDK] strength=2.5", "Should have been rejected")
    except (ValidationError, OfSpectrumError) as e:
        if "strength" in str(e).lower() or "2.0" in str(e):
            log_pass("[SDK] strength=2.5", "Correctly rejected")
        else:
            log_warn("[SDK] strength=2.5", f"Rejected: {e}")
    except Exception as e:
        log_warn("[SDK] strength=2.5", f"Error: {e}")

def test_sdk_invalid_api_key():
    """Test invalid API key via SDK"""
    print("\n--- [SDK] Testing Invalid API Key ---")
    try:
        client = OfSpectrum(api_key="invalid_key", base_url=BASE_URL)
        client.tokens.list()
        log_fail("[SDK] Invalid API key", "Should have raised error")
    except AuthenticationError:
        log_pass("[SDK] Invalid API key", "Correctly raised AuthenticationError")
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e) or "Invalid" in str(e):
            log_pass("[SDK] Invalid API key", f"Rejected: {e}")
        else:
            log_fail("[SDK] Invalid API key", f"Unexpected: {e}")

# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("Complete API Test - SDK + Direct URL")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")

    # Setup - use current directory or temp directory
    test_dir = Path.cwd() / ".test_tmp"
    test_dir.mkdir(parents=True, exist_ok=True)

    test_audio = str(test_dir / "test_input.wav")
    watermarked_url = str(test_dir / "watermarked_url.wav")
    watermarked_sdk = str(test_dir / "watermarked_sdk.wav")

    # Create test audio if not exists
    if not Path(test_audio).exists():
        print("\n[Setup] Creating test audio file...")
        create_test_audio(test_audio)
        print(f"  Created: {test_audio}")
    else:
        print(f"\n[Setup] Using existing test audio: {test_audio}")

    # Initialize SDK clients
    print("\n[Setup] Initializing SDK clients...")
    client_a = OfSpectrum(api_key=API_KEY_USER_A, base_url=BASE_URL)
    client_b = OfSpectrum(api_key=API_KEY_USER_B, base_url=BASE_URL)
    print("  Clients ready")

    try:
        # ================================================================
        # PART 1: Direct URL Tests
        # ================================================================
        print("\n" + "=" * 70)
        print("PART 1: Direct URL (curl-style) Tests")
        print("=" * 70)

        # Get tokens
        tokens = test_url_tokens_list(API_KEY_USER_A)
        if not tokens:
            print("ERROR: No tokens found via URL")
            return

        token_id = tokens[0]["id"]
        print(f"\n  Using token: {token_id}")

        # Quotas
        test_url_quotas_all(API_KEY_USER_A)

        # Encode
        encoded_url = test_url_encode(API_KEY_USER_A, token_id, test_audio, watermarked_url)

        # Decode
        if encoded_url and os.path.exists(encoded_url):
            test_url_decode(API_KEY_USER_A, encoded_url)

        # Notebooks
        notebooks = test_url_notebooks_list(API_KEY_USER_A, token_id)

        if notebooks:
            note_id = notebooks[0]["id"]

            # Media list
            test_url_notebooks_media_list(API_KEY_USER_A, note_id)

            # Media upload
            media = test_url_media_upload(API_KEY_USER_A, note_id, test_audio)

            if media:
                media_id = media.get("id")
                if media_id:
                    # Signed URL
                    test_url_media_signed_url(API_KEY_USER_A, media_id)

            # Cross-user access
            test_url_cross_user_access(API_KEY_USER_B, note_id)

        # Invalid API key
        test_url_invalid_api_key()

        # ================================================================
        # PART 2: SDK Tests
        # ================================================================
        print("\n" + "=" * 70)
        print("PART 2: SDK Tests")
        print("=" * 70)

        token = test_sdk_tokens(client_a)
        if not token:
            print("ERROR: No tokens found via SDK")
        else:
            token_id = token.id

        test_sdk_quotas(client_a)

        encoded_sdk = test_sdk_encode(client_a, token_id, test_audio, watermarked_sdk)

        if encoded_sdk and os.path.exists(encoded_sdk):
            test_sdk_decode(client_a, encoded_sdk)

        test_sdk_notebooks(client_a, token_id, test_audio)

        test_sdk_strength_validation(client_a, token_id, test_audio)

        test_sdk_invalid_api_key()

        # ================================================================
        # Summary
        # ================================================================
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        print(f"\n✅ Passed: {len(results['passed'])}")
        for t in results['passed']:
            print(f"   - {t}")

        if results['warnings']:
            print(f"\n⚠️  Warnings: {len(results['warnings'])}")
            for t, msg in results['warnings']:
                print(f"   - {t}: {msg}")

        if results['failed']:
            print(f"\n❌ Failed: {len(results['failed'])}")
            for t, msg in results['failed']:
                print(f"   - {t}: {msg}")

        print("\n" + "=" * 70)
        total = len(results['passed']) + len(results['failed'])
        pass_rate = len(results['passed']) / total * 100 if total > 0 else 0
        print(f"Pass Rate: {pass_rate:.1f}% ({len(results['passed'])}/{total})")
        print("=" * 70)

    finally:
        client_a.close()
        client_b.close()

if __name__ == "__main__":
    main()
