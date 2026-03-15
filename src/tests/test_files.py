import json
import os
import stat
from pathlib import Path

import pytest

from files.File import validate_file, read_file_content, read_json_file


def test_validate_file(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    # Should not raise
    validate_file(str(test_file))

    # Test non-existent file
    with pytest.raises(ValueError, match="File does not exist"):
        validate_file(str(tmp_path / "missing.txt"))

    # Test directory instead of file
    with pytest.raises(ValueError, match="Path is not a file"):
        validate_file(str(tmp_path))

    # Test unreadable file
    # Ensure it's read-only/unreadable (on some OS like windows this can be tricky,
    # but we can simulate the permission error)
    unreadable_file = tmp_path / "no_read.txt"
    unreadable_file.write_text("secret")
    os.chmod(unreadable_file, 000)

    # Check if os actually applied it (on Windows it might still be readable)
    if not os.access(unreadable_file, os.R_OK):
        with pytest.raises(ValueError, match="File is not readable"):
            validate_file(str(unreadable_file))

    # Restore permissions to allow cleanup
    os.chmod(unreadable_file, stat.S_IREAD | stat.S_IWRITE)


def test_read_file_content(tmp_path: Path):
    # Plain text
    txt_file = tmp_path / "doc.md"
    txt_file.write_text("Markdown **content**", encoding="utf-8")
    assert read_file_content(str(txt_file)) == "Markdown **content**"

    # Unsupported extension
    unsupported_file = tmp_path / "doc.xyz"
    unsupported_file.write_text("xyz")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        read_file_content(str(unsupported_file))


def test_read_json_file(tmp_path: Path):
    json_file = tmp_path / "data.json"
    json_data = {"key": "value"}
    json_file.write_text(json.dumps(json_data), encoding="utf-8")

    assert read_json_file(str(json_file)) == json_data

    # Invalid JSON
    invalid_file = tmp_path / "bad.json"
    invalid_file.write_text("Not JSON")
    with pytest.raises(ValueError, match="Error decoding JSON from file"):
        read_json_file(str(invalid_file))
