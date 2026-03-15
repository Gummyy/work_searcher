import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from config.Config import Config
from config.types import (
    FileOrContent,
    Document,
    JobspyArgs,
    APICalls,
    Config as ConfigModel,
)


def test_file_or_content_validators(tmp_path: Path):
    # Test valid content directly
    foc = FileOrContent(content="Some direct content")
    assert foc.content == "Some direct content"
    assert foc.file is None

    # Test file reading
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello file", encoding="utf-8")

    foc_file = FileOrContent(file=str(test_file))
    assert foc_file.file == str(test_file)
    assert foc_file.content == "Hello file"

    # Test failing conditions
    with pytest.raises(
        ValueError, match="At least one of 'file' or 'content' must be provided"
    ):
        FileOrContent()

    with pytest.raises(ValueError, match="'content' must not be empty"):
        FileOrContent(content="   ")

    test_empty_file = tmp_path / "empty.txt"
    test_empty_file.write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError, match="'content' must not be empty"):
        FileOrContent(file=str(test_empty_file))


def test_jobspy_args_validators():
    # Test normalization to list
    args = JobspyArgs(
        site_name="linkedin",
        search_terms="engineer",
        location="NY",
        job_type="fulltime",
    )
    assert args.site_name == ["linkedin"]
    assert args.search_terms == ["engineer"]
    assert args.location == ["NY"]
    assert args.job_type == ["fulltime"]

    # Test invalid site
    with pytest.raises(ValidationError, match="Invalid site_name 'invalid_site'"):
        JobspyArgs(
            site_name=["linkedin", "invalid_site"], search_terms=["a"], location=["b"]
        )

    # Test invalid job type
    with pytest.raises(ValidationError, match="Invalid job_type 'random'"):
        JobspyArgs(
            site_name=["linkedin"],
            search_terms=["a"],
            location=["b"],
            job_type=["fulltime", "random"],
        )


def test_config_model_validators():
    # Test duplicate categories
    foc = FileOrContent(content="text")
    doc1 = Document(category="dev", description="dev", resume=foc, cover_letter=foc)
    doc2 = Document(
        category="dev", description="another dev", resume=foc, cover_letter=foc
    )

    with pytest.raises(
        ValidationError, match="Document categories must be unique across documents."
    ):
        ConfigModel(profile=foc, preferences=foc, documents=[doc1, doc2])


def test_config_loader(tmp_path: Path):
    config_file = tmp_path / "config.json"

    valid_data = {
        "profile": {"content": "profile text"},
        "preferences": {"content": "prefs text"},
        "documents": [
            {
                "category": "cat1",
                "description": "desc1",
                "resume": {"content": "res1"},
                "cover_letter": {"content": "cl1"},
            }
        ],
    }
    config_file.write_text(json.dumps(valid_data), encoding="utf-8")

    config = Config(str(config_file))
    model = config.get_config()
    assert model.profile.content == "profile text"
    assert len(model.documents) == 1


def test_config_loader_errors(tmp_path: Path):
    # Missing file
    with pytest.raises(ValueError, match="Invalid config path"):
        Config(str(tmp_path / "missing.json"))

    # Invalid JSON
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("Not a json", encoding="utf-8")
    with pytest.raises(ValueError, match="Error reading config file"):
        Config(str(invalid_file))

    # Invalid content (missing required fields)
    bad_config = tmp_path / "bad.json"
    bad_config.write_text(json.dumps({"profile": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid config content in file"):
        Config(str(bad_config))
