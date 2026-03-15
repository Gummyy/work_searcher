import json
import os
import subprocess
from pathlib import Path
from typing import Any

ODF_EXTENSIONS = {".odt", ".ods", ".odp", ".odg", ".odc", ".odf", ".odi", ".odm"}
PANDOC_SUPPORTED_EXTENSIONS = {
    ".txt": "plain",
    ".rtf": "rtf",
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".latex": "latex",
    ".docx": "docx",
    ".doc": "doc",
    ".odt": "odt",
    ".pdf": "pdf",
}


def validate_file(file_path: str) -> None:
    """Validates that a path points to an existing, readable file.

    Args:
        file_path (str): The path to validate.

    Raises:
        ValueError: If the path does not exist, is not a file, or is not readable.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File does not exist: {file_path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    if not os.access(path, os.R_OK):
        raise ValueError(f"File is not readable: {file_path}")


def read_file_content(file_path: str) -> str:
    """Reads a file and returns its content as GitHub-flavoured Markdown.

    All formats listed in PANDOC_SUPPORTED_EXTENSIONS are converted to GFM
    via pandoc. The pandoc executable is resolved from the PANDOC_PATH
    environment variable, defaulting to ``pandoc`` if the variable is not set.

    Args:
        file_path (str): Path to the file to read.

    Raises:
        ValueError: If the file extension is not in PANDOC_SUPPORTED_EXTENSIONS.
        subprocess.CalledProcessError: If pandoc exits with a non-zero return code.

    Returns:
        str: The file content rendered as GitHub-flavoured Markdown.
    """
    path = Path(file_path)
    extension = path.suffix.lower()
    pandoc_path = os.environ.get("PANDOC_PATH", "pandoc")
    if pandoc_path is None:
        raise EnvironmentError(
            "PANDOC_PATH environment variable is not set. Please set it to the path of the pandoc executable."
        )

    if extension not in PANDOC_SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {extension}")
    else:
        return subprocess.run(
            [
                pandoc_path,
                f"--from={PANDOC_SUPPORTED_EXTENSIONS[extension]}",
                "--to=gfm",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout


def read_json_file(file_path: str) -> dict[str, Any]:
    """Reads and parses a JSON file.

    Args:
        file_path (str): Path to the JSON file.

    Raises:
        ValueError: If the file cannot be opened or contains invalid JSON.

    Returns:
        dict[str, Any]: The parsed JSON content.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Error decoding JSON from file: {file_path}") from e
    except OSError as e:
        raise ValueError(f"Error loading file: {file_path}") from e


def convert_to_pdf(file_path: Path) -> None:
    """Converts a file to PDF if it is an ODF format.

    If the file has an ODF extension, it is converted to PDF using LibreOffice
    in headless mode. The resulting PDF is saved in the same directory. If the
    file is not an ODF format, no action is taken.

    Args:
        file_path (Path): Path to the file to convert.

    Raises:
        EnvironmentError: If the required conversion tool is not configured.
        RuntimeError: If the conversion process fails or returns a non-zero exit code.
    """
    if file_path.suffix.lower() in ODF_EXTENSIONS:
        _convert_odt_to_pdf(file_path)
    elif file_path.suffix.lower() in PANDOC_SUPPORTED_EXTENSIONS:
        _convert_rich_text_to_pdf(file_path)


def _convert_odt_to_pdf(file_path: Path) -> None:
    """Converts a file to PDF using LibreOffice in headless mode.

    Reads the LibreOffice executable path from the LIBREOFFICE_PATH environment
    variable. If the variable is not set, a warning is logged and the conversion
    is skipped. Set LIBREOFFICE_PATH in a .env file or your shell environment:
      - Windows example: C:\\Program Files\\LibreOffice\\program\\soffice.exe
      - Unix example:    libreoffice

    Args:
        file_path (Path): Path to the file to convert. The resulting PDF is
            placed in the same directory.

    Raises:
        subprocess.CalledProcessError: If LibreOffice exits with a non-zero
            return code.
    """
    libreoffice_path = os.environ.get("LIBREOFFICE_PATH")
    if libreoffice_path is None:
        raise EnvironmentError(
            "LIBREOFFICE_PATH environment variable is not set. Please set it to the path of the LibreOffice executable."
        )
    try:
        subprocess.run(
            [
                libreoffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(file_path.parent),
                str(file_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"PDF conversion failed for '{file_path.name}': {e.stderr}"
        ) from e


def _convert_rich_text_to_pdf(file_path: Path) -> None:
    """Converts a rich text file to PDF using pandoc.

    Reads the pandoc executable path from the PANDOC_PATH environment variable.
    If the variable is not set, a warning is logged and the conversion is skipped.
    Set PANDOC_PATH in a .env file or your shell environment:
      - Windows example: C:\\Program Files\\Pandoc\\pandoc.exe
      - Unix example:    pandoc

    Args:
        file_path (Path): Path to the file to convert. The resulting PDF is
            placed in the same directory with the same base name.

    Raises:
        subprocess.CalledProcessError: If pandoc exits with a non-zero return code.
    """
    pandoc_path = os.environ.get("PANDOC_PATH")
    if pandoc_path is None:
        raise EnvironmentError(
            "PANDOC_PATH environment variable is not set. Please set it to the path of the pandoc executable."
        )
    output_pdf = file_path.with_suffix(".pdf")
    try:
        subprocess.run(
            [
                pandoc_path,
                str(file_path),
                "-o",
                str(output_pdf),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"PDF conversion failed for '{file_path.name}': {e.stderr}"
        ) from e
