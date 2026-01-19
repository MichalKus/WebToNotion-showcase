"""JSON payload cleaning utilities."""


def clean_json(payload: str) -> str:
    """
    Clean JSON payload by removing markdown code blocks and comments.

    This function removes:
    - Opening/closing markdown code block markers (```json, ```)
    - Comments before code blocks (# ```json, # ```)
    - Leading/trailing whitespace

    Args:
        payload: Raw JSON payload string that may contain markdown formatting

    Returns:
        Cleaned JSON payload string

    Example:
        >>> payload = '```json\n{"key": "value"}\n```'
        >>> clean_json(payload)
        '{"key": "value"}'

        >>> payload = '# ```json\n{"key": "value"}\n# ```'
        >>> clean_json(payload)
        '{"key": "value"}'
    """
    cleaned_payload = payload.strip()

    # Remove opening markdown code block
    if cleaned_payload.startswith("```"):
        cleaned_payload = "\n".join(cleaned_payload.split("\n")[1:])

    # Remove closing markdown code block
    if cleaned_payload.endswith("```"):
        cleaned_payload = cleaned_payload.rsplit("\n", 1)[0]

    # Remove comments before code blocks
    if "# ```json" in cleaned_payload:
        cleaned_payload = cleaned_payload.replace("# ```json", "").replace("# ```", "")

    return cleaned_payload.strip()
