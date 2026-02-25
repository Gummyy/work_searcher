# Work Searcher

The software developed in this repository is used to enhance the job offering applications of the user.

## Features

The application processes job offerings matching user criteria and performs the following for each:
*   **Candidate Rank**: Rankings how suitable the user is for the position based on their profile.
*   **Offering Rank**: Rankings how suitable the job offering is for the user based on their preferences.
*   **Document Selection**: Chooses the most relevant resume and cover letter category.
*   **Customization**: Copies and renames the selected resume and cover letter (e.g., `resume_{company}_{position}.pdf`). It also modifies the cover letter to highlight soft skills demanded by the offering.
*   **Summary Generation**: detailed Excel file containing ranks, explanations, and optional data like commute time, salary, and start date proximity.

## Configuration

The user provides a `config.json` file containing:
*   A list of categorized resumes and cover letters.
*   Job criteria (translating to API parameters).
*   **User's Profile**: A detailed text description of every skill, education, and job experience.
*   **User's Preferences**: A text file describing the user's dream job (industry, company size, remote work, etc.).

## Environment

This repository contains code developed in Python 3.13.7.

### Setup

To set up the environment:

1.  Activate the virtual environment (PowerShell):
    ```powershell
    .\work_searcher_env\Scripts\Activate.ps1
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3.  Configure environment variables in `.env`.

## Tests

This repository uses `pytest`. Run tests with:

```bash
pytest
```
