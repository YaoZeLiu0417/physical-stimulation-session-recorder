from pathlib import Path


REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"


def _requirement_specs() -> tuple[str, ...]:
    specs = []
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        spec = raw_line.split("#", 1)[0].strip()
        if spec:
            specs.append(spec)
    return tuple(specs)


def test_production_requirements_use_approved_webrtc_stack() -> None:
    assert _requirement_specs() == (
        "streamlit==1.37.1",
        "streamlit-webrtc==0.63.4",
        "aiortc==1.15.0",
        "av==17.0.0",
        "numpy>=1.24,<2.0",
        "requests>=2.31,<3",
        "protobuf<5",
        "python-dotenv>=1.0,<2",
    )
