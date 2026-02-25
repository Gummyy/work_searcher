# AGENTS.md

In this file, agents are provided instructions to efficiently analyze prompts and keep up with the coding standards of the repository.

# Interpreting the prompts

**CRITICAL RULES:**
- The proposed edits **MUST BE MINIMAL** and **restrained to exactly what the prompt says**
- In case a bug is seen during the edit, simply mention it in the chat, but **NEVER EDIT SOMETHING YOU ARE NOT ASKED TO**
- In case the instructions aren't clear enough, ask for more details (using precise questions) before attempting to make an incomplete update
- When investigating the meaning of the prompt, explain what you have understood (what you would do) and what you need to know before completely solving the task you are given.

# Coding standards

The following sections define the coding standards that **MUST** be followed when working on this repository. These rules ensure code consistency, readability, and maintainability.

Black formatter is used in every file for proper spacing / readability.
There are specific coding rules which should be followed as much as possible when editing the repository.

## Comments

**CRITICAL RULES:**
- Comments are used to describe the code. They should never mention a "You", as the code isn't intended for any person. Neither should they mention the prompt which generated them (explanations can eventually be added in the chat, but **NEVER IN THE CODE**).
- Comments aren't a substitute for writing readable code. They should be as light as possible and there shouldn't be much of them
- Use comments to explain "why", not "what" (the code itself should explain "what")
- Remove commented-out code rather than leaving it in the codebase, unless uncertain of what the best version should be

## Variables

### Naming conventions

- Variable names use snake_case and must be as clear as possible (exception: `i, j, k, l` are acceptable for loop iterators)
- Lists and sets use plural names indicating what they hold (e.g., `entities`, `documents`, `relationships`)
- Variables in CAPITAL_LETTERS are always constants

### Types

- Variables may use type hints when it helps readability, but are mostly defined without
- Always use type hints in function signatures (see Functions section)
- Use the most appropriate types for variables, including :
    - the `datetime.datetime` module for datetime manipulation
    - r-strings for regexes
    - specific `BaseModel` or `TypedDict` objects defined in `types.py` in case a dict requiring sepcific values is used by a function.

### Usage rules
- Every defined variable must be used later in the code
- Use `_` as the name for unused variables (e.g., in tuple unpacking). Example:

```python
elements, _ = get_elements_and_indices()
```

- Variables used only once should not be declared separately. Use the value directly instead:

```python
# Wrong syntax :
temp_result = compute_res()
final_result = format_res(temp_result)

# Correct syntax :
final_result = format_res(compute_res())
```

## Functions

### Naming conventions

- Function names use snake_case
- Function names should be verbs or verb phrases that clearly describe what the function does

### Function design

- Functions that are so specific they can ever be called only once should be avoided, unless they perform critical actions which require advanced testing. Prioritize keeping code concise and in context.
- Functions should do one thing and do it well (Single Responsibility Principle)

### Documentation (REQUIRED)
- Every function must have type hints (as complete as possible) and a docstring
- Example of a properly documented function:

```python
def draw_rectangle(
    image: Image.Image,
    bounding_box: list[int],
    outline: Optional[str] = None,
    fill: Optional[str] = None,
    width: int = 2,
) -> Image.Image:
    """Draws a rectangle on an image.

    Args:
        image (Image.Image): The image to draw the rectangle on.
        bounding_box (list[int]): The bounding box to draw the rectangle in.
        outline (str, optional): The color of the rectangle outline. Defaults to None, in which case the best matching color is computed with colors.py::determine_annotation_color.
        fill (str, optional): The color to fill the rectangle with. Defaults to None, in which case the best matching color is computed with colors.py::determine_annotation_color.
        width (int, optional): The width of the rectangle outline. Defaults to 2.

    Returns:
        Image.Image: The image with the rectangle drawn on it.
    """
    ...
```

### Docstring requirements

- Description of what the function does
- `Args:` section with all arguments, each including:
    - name
    - type (be as complete as possible). Define custom `TypedDict` or `BaseModel` objects in `types.py` files to enhance readability
    - short description with default value behavior (e.g., what happens when a default is `None`)
- `Raises:` section listing errors the function can raise (if any)
- `Returns:` section with return type and description (omit if function returns nothing)

## Classes

### Naming conventions

- Class names use CamelCase (PascalCase)
- Private methods/attributes start with a single underscore `_` (uncommon)
- "Magic" or strongly private methods/attributes use double underscore `__` (extremely rare)

### Documentation

- Classes must have a docstring describing their purpose
- The docstring should document all class attributes and their types
- Each method follows the same documentation rules as functions

### Design principles
- Keep classes focused and cohesive
- Use composition over inheritance when possible
- Prefer dataclasses or Pydantic models for simple data structures

Example:
```python
class SceneGraphProcessor:
    """Processes scene graphs for storage and retrieval.
    
    Attributes:
        neo4j_client (Neo4jClientWrapper): The Neo4j database client.
        qdrant_client (QdrantClientWrapper): The Qdrant vector database client.
        embedding_model (str): The name of the embedding model to use.
    """
    
    def __init__(
        self,
        neo4j_client: Neo4jClientWrapper,
        qdrant_client: QdrantClientWrapper,
        embedding_model: str = "default"
    ):
        self.neo4j_client = neo4j_client
        self.qdrant_client = qdrant_client
        self.embedding_model = embedding_model
```

## Error Handling

### Principles

- Catch specific exceptions rather than using bare `except:`
- Let exceptions propagate if you can't handle them meaningfully
- Log errors with appropriate context before re-raising
- Don't silently swallow exceptions

### When to use try/except
- When you can recover from the error
- When you need to clean up resources
- When you need to add context to an error message

Example:
```python
try:
    document = read_document(path)
except FileNotFoundError:
    raise ValueError(f"Document not found at path: {path}")
except PermissionError:
    logger.error(f"Permission denied reading {path}")
    raise
```

## File Organization

### Module structure

- Each directory should have an `__init__.py` file
- Related functionality goes in the same directory
- Use `types.py` files for type definitions within each module
- Keep files focused on a single concern

### When to create a new file

- When adding a new major feature or component
- When a file grows beyond ~500 lines
- When a logical grouping of functions/classes emerges

### When to add to existing files
- When extending existing functionality
- When the addition is closely related to existing code
- When the file is still reasonably sized

## Testing

### Test organization

- All tests go in the `tests/` directory
- Test files must be named `test_<feature>.py`
- Test functions must be named `test_<specific_behavior>`
- Use fixtures for common setup/teardown

### What to test
- All public functions and methods
- Edge cases and error conditions
- Integration points between modules

### Example

```python
def test_create_scene_graph_from_image():
    """Test scene graph creation from a valid image file."""
    image_path = "tests/images/sample.jpg"
    scene_graph = create_scene_graph(image_path)
    
    assert scene_graph is not None
    assert len(scene_graph.entities) > 0
    assert len(scene_graph.relationships) > 0
```

---

# Summary: Critical Rules

When working on this codebase, always:

1. ✅ Use snake_case for functions and variables, CamelCase for classes
2. ✅ Provide complete type hints and docstrings for all functions
3. ✅ Never mention "you" or prompts in comments
4. ✅ Use `_` for unused variables
5. ✅ Don't declare variables used only once
6. ✅ Keep functions focused and under 50 lines when possible
8. ✅ Catch specific exceptions, not bare `except:`
9. ✅ Write tests for all public functions
10. ✅ Use Black formatter for all code
