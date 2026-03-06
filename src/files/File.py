import json
import os
import subprocess
from pathlib import Path
from typing import Any

from odf import text, teletype
from odf.opendocument import load

from logger import logger

PLAIN_TEXT_EXTENSIONS = {".txt", ".rtf", ".md"}
ODF_EXTENSIONS = {".odt", ".ods", ".odp", ".odg", ".odc", ".odf", ".odi", ".odm"}


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
    """Reads a file and returns its text content.

    The reading strategy is determined by the file extension:
    - Plain text formats (.txt, .rtf, .md) are read directly as UTF-8 text.
    - ODF formats (.odt, .ods, .odp, .odg, .odc, .odf, .odi, .odm) are
      parsed with odfpy and their text paragraphs are extracted.

    Args:
        file_path (str): Path to the file to read.

    Raises:
        ValueError: If the file extension is not supported.

    Returns:
        str: The text content of the file.
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension in PLAIN_TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8")
    if extension in ODF_EXTENSIONS:
        return _read_odf_content(file_path)
    raise ValueError(
        f"Unsupported file extension '{extension}'. "
        f"Supported extensions: {sorted(PLAIN_TEXT_EXTENSIONS | ODF_EXTENSIONS)}"
    )


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


def _read_odf_content(file_path: str) -> str:
    """Extracts paragraph text from an ODF file using odfpy.

    Args:
        file_path (str): Path to the ODF file.

    Returns:
        str: Concatenated paragraph text, separated by newlines.
    """
    doc = load(file_path)
    paragraphs = doc.getElementsByType(text.P)
    return "\n".join(teletype.extractText(p) for p in paragraphs)


def odt_to_markdown(job_path: Path) -> str:
    """Converts an ODT file to a Markdown string using pandoc.

    Args:
        job_path (Path): Path to the .odt file.

    Returns:
        str: The file contents as GitHub-Flavoured Markdown.

    Raises:
        subprocess.CalledProcessError: If the pandoc subprocess exits with a non-zero code.
    """
    pandoc_path = os.environ.get("PANDOC_PATH", "pandoc")
    return subprocess.run(
        [pandoc_path, "--from=odt", "--to=gfm", str(job_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def convert_to_pdf(file_path: Path) -> None:
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
    if not libreoffice_path:
        logger.warning(
            "LIBREOFFICE_PATH is not set — skipping PDF conversion for '%s'.",
            file_path.name,
        )
        return
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
        logger.info("Converted '%s' to PDF.", file_path.name)
    except subprocess.CalledProcessError as e:
        logger.error("PDF conversion failed for '%s': %s", file_path.name, e.stderr)
