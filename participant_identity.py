import re


SUBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_subject_id(subject_id: str) -> str:
    if not isinstance(subject_id, str):
        raise ValueError("participant identifier is invalid")
    safe_subject_id = subject_id.strip()
    if safe_subject_id != subject_id or not SUBJECT_ID_RE.fullmatch(safe_subject_id):
        raise ValueError("participant identifier is invalid")
    return safe_subject_id
