import pytest

from participant_identity import validate_subject_id


@pytest.mark.parametrize("subject_id", ["sub-001", "A", "user_name-2"])
def test_validate_subject_id_accepts_exact_safe_identifiers(subject_id):
    assert validate_subject_id(subject_id) == subject_id


@pytest.mark.parametrize(
    "subject_id",
    [
        "",
        " sub-001",
        "sub-001 ",
        "../subject",
        "a" * 65,
        "sub/001",
        "sub\\001",
        ".subject",
        "sub.name",
        "sub?001",
        "sub\n001",
        "sub\t001",
        "sub\x00001",
    ],
)
def test_validate_subject_id_rejects_unsafe_strings(subject_id):
    with pytest.raises(ValueError, match="participant identifier is invalid"):
        validate_subject_id(subject_id)


@pytest.mark.parametrize("subject_id", [None, 123, b"sub-001"])
def test_validate_subject_id_rejects_non_strings(subject_id):
    with pytest.raises(ValueError, match="participant identifier is invalid"):
        validate_subject_id(subject_id)
