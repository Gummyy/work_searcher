from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from files.File import read_file_content, validate_file


class FileOrContent(BaseModel):
    """A model that holds either a file path or a raw string value.

    At least one of the fields must be provided. If only 'file' is given,
    'content' is automatically populated from the file's text.

    Attributes:
        file (str, optional): Path to a readable file. Defaults to None.
        content (str, optional): Raw string content. Defaults to None.
    """

    file: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)

    @field_validator("file")
    @classmethod
    def validate_file_exists_and_readable(cls, v: Optional[str]) -> Optional[str]:
        """Validates that the file path points to an existing, readable file.

        Args:
            v (str, optional): The file path to validate.

        Raises:
            ValueError: If the path does not exist, is not a file, or is not readable.

        Returns:
            str | None: The validated file path, or None if not provided.
        """
        if v is None:
            return v
        validate_file(v)
        return v

    @model_validator(mode="after")
    def populate_and_validate_content(self) -> "FileOrContent":
        """Ensures content is populated and non-empty.

        If only 'file' is provided, reads the file and populates 'content'.
        Raises an error if neither field is set or if content ends up empty.

        Raises:
            ValueError: If both fields are None, or if content is empty.

        Returns:
            FileOrContent: The validated model instance.
        """
        if self.file is None and self.content is None:
            raise ValueError("At least one of 'file' or 'content' must be provided.")
        if self.content is None:
            self.content = read_file_content(self.file)
        if not self.content.strip():
            raise ValueError("'content' must not be empty.")
        return self


class LinkedinAPI(BaseModel):
    client_id: str = Field(description="LinkedIn API client ID")
    client_secret: str = Field(description="LinkedIn API client secret")


class IndeedAPI(BaseModel):
    api_key: str = Field(description="Indeed API key")


class API_settings(BaseModel):
    linkedin: LinkedinAPI
    indeed: IndeedAPI


class Config(BaseModel):
    profile: FileOrContent
    preferences: FileOrContent
    apis: API_settings
