import os
import shutil
import sys
import zipfile
from pathlib import Path

from core.networking import NetworkRequestError, shared_http_client_registry
from main_logger import logger

_HTTP_CLIENT = shared_http_client_registry().acquire(
    "ffmpeg-installer",
    client_options={"follow_redirects": True},
)


def install_ffmpeg(target_directory=".",
                   url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                   log=None):
    """
    Downloads the FFmpeg zip archive from the specified URL, extracts ONLY
    ffmpeg.exe to the target directory (root), and deletes the downloaded
    zip file and any other extracted contents.

    Args:
        target_directory (str or Path): The directory where ffmpeg.exe
                                        should be placed. Defaults to the
                                        current working directory (".").
                                        This is NOT relative to sys.executable.
        url (str): The URL to download the FFmpeg zip archive from.
        log (callable or None): Optional sink for user-facing messages (e.g. the
                                AI Hub install log). Errors are reported through
                                it *and* the file logger, so the real failure
                                reason (network reset, bad zip, ...) reaches the
                                install window instead of just "failed".

    Returns:
        bool: True if ffmpeg.exe was successfully placed in the target
              directory, False otherwise.
    """
    def _emit(msg):
        logger.info(msg)
        if log is not None:
            try:
                log(msg)
            except Exception:
                pass

    target_dir = Path(target_directory).resolve()
    # Ensure target directory exists, create if not
    target_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe_name = "ffmpeg.exe"
    target_ffmpeg_path = target_dir / ffmpeg_exe_name

    # --- 1. Check if ffmpeg.exe already exists ---
    if target_ffmpeg_path.exists():
        logger.info(f"'{ffmpeg_exe_name}' already exists in '{target_dir}'. Skipping installation.")
        return True

    # --- 2. Download the zip file ---
    # Use a temporary name for the download in the target directory
    zip_filename = "ffmpeg_download_temp.zip"
    zip_filepath = target_dir / zip_filename

    logger.info(f"Target directory: {target_dir}")
    _emit(f"Downloading FFmpeg from {url}...")
    try:
        # Use stream=True for potentially large files and add a timeout
        with _HTTP_CLIENT.stream("GET", url, timeout=60) as response:
            _HTTP_CLIENT.raise_for_status(response)
            with open(zip_filepath, 'wb') as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
        logger.info(f"Download complete: '{zip_filepath}'")

    except NetworkRequestError as e:
        _emit(f"Error downloading file: {e}")
        # Clean up potentially incomplete download
        if zip_filepath.exists():
            os.remove(zip_filepath)
        return False
    except Exception as e:
        _emit(f"An unexpected error occurred during download: {e}")
        if zip_filepath.exists():
            os.remove(zip_filepath)
        return False

    # --- 3. Extract ONLY ffmpeg.exe ---
    extracted = False
    logger.info(f"Extracting '{ffmpeg_exe_name}'...")
    try:
        with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
            # Find the specific file within the zip archive
            ffmpeg_path_in_zip = None
            # Common structures are like 'ffmpeg-xxxxx-win64-gpl/bin/ffmpeg.exe'
            # We search for any path ending in '/bin/ffmpeg.exe' or just 'ffmpeg.exe'
            possible_paths = [m.filename for m in zip_ref.infolist() if m.filename.endswith(ffmpeg_exe_name) and not m.is_dir()]

            if not possible_paths:
                _emit(f"Error: '{ffmpeg_exe_name}' not found within the zip file '{zip_filepath}'.")
                return False # Failure, ffmpeg.exe not found

            # Prefer a path that includes '/bin/' if multiple matches exist
            bin_path = next((p for p in possible_paths if '/bin/' in p), None)
            ffmpeg_path_in_zip = bin_path if bin_path else possible_paths[0] # Fallback to the first match

            logger.info(f"Found '{ffmpeg_exe_name}' at: '{ffmpeg_path_in_zip}' inside the zip.")

            # Extract the single file directly to the target path
            # We open the file within the zip and write its contents to the target file
            with zip_ref.open(ffmpeg_path_in_zip) as source, open(target_ffmpeg_path, 'wb') as target:
                shutil.copyfileobj(source, target) # Efficiently copy file object contents

            logger.info(f"Successfully extracted '{ffmpeg_exe_name}' to '{target_ffmpeg_path}'")
            extracted = True
            return True # Success

    except zipfile.BadZipFile:
        _emit(f"Error: Downloaded file '{zip_filepath}' is not a valid zip file.")
        return False # Failure
    except Exception as e:
        _emit(f"An error occurred during extraction: {e}")
        # If extraction failed but ffmpeg.exe was partially created, remove it
        if target_ffmpeg_path.exists():
             try:
                 os.remove(target_ffmpeg_path)
             except OSError:
                 pass # Ignore error if removal fails
        return False # Failure
    finally:
        # --- 4. Clean up the downloaded zip file ---
        if zip_filepath.exists():
            logger.info(f"Deleting temporary file '{zip_filepath}'...")
            try:
                os.remove(zip_filepath)
                logger.info("Temporary file deleted.")
            except OSError as e:
                logger.info(f"Warning: Could not delete temporary file '{zip_filepath}': {e}")

# --- Example Usage ---
if __name__ == "__main__":
    logger.info(f"Current working directory: {Path.cwd()}")
    logger.info(f"Python executable directory: {Path(sys.executable).parent}")

    # Install ffmpeg.exe directly into the current working directory
    success = install_ffmpeg()

    if success:
        logger.info("\nFFmpeg installation check successful.")
        # Verify it exists
        if (Path.cwd() / "ffmpeg.exe").exists():
            logger.info("'ffmpeg.exe' is present in the current working directory.")
        else:
             logger.info("Verification failed: 'ffmpeg.exe' not found where expected.")
    else:
        logger.info("\nFFmpeg installation failed.")
