# Streamlit Deployment Dependency Recovery Design

## Context

The controlled showcase subdomain is reserved, but the Streamlit backend never
becomes healthy. The repository currently pins `av==11.0.0`; PyPI publishes that
release only as a source archive, so Community Cloud must compile the FFmpeg
binding during deployment. The deployment fails before `showcase_app.py` can
start. This is a dependency installation failure, not an application-secret or
password-flow failure.

## Goal

Make the existing private repository install reliably on Streamlit Community
Cloud while preserving the recorder and synthetic showcase behavior.

## Selected Approach

Update only the WebRTC dependency set in `requirements.txt`:

- `streamlit-webrtc==0.63.4`
- `aiortc==1.15.0`
- `av==17.0.0`

This is a compatible set: `streamlit-webrtc` requires `aiortc>=1.11`, and
`aiortc==1.15.0` requires `av>=14,<18`. `av==17.0.0` publishes Linux wheels for
Python 3.10 and ABI3 Linux wheels for newer supported Python versions, avoiding
the source build that blocks deployment.

Keep `streamlit==1.37.1`, NumPy, Requests, Protobuf, and python-dotenv unchanged.
Do not split or duplicate the showcase entry point, change questionnaire logic,
alter recorder behavior, or expose repository content.

## Verification

1. Add a focused requirements contract test that fails on the old pins and
   requires the approved compatible versions.
2. Resolve/download the complete requirements set using Linux binary
   distributions for Python 3.10, which is the project's intended Community
   Cloud runtime. Separately confirm that the approved WebRTC releases provide
   binary distributions compatible with Python 3.13. The retained `numpy<2.0`
   constraint does not publish Python 3.13 wheels, so the deployed app must use
   Python 3.10 rather than broadening unrelated dependency constraints.
3. Run the focused showcase tests and the complete private test suite.
4. Compile Python sources and run Git patch checks.
5. Push only to the private repository, merge through a private PR, and confirm
   anonymous source access still returns `404`.
6. Confirm the Streamlit app uses Python 3.10, wait for it to rebuild, then
   require a healthy backend response and verify fail-closed access,
   wrong-password rejection, correct-password entry, all four synthetic steps,
   and restart.

## Failure And Rollback

Do not merge if dependency resolution or tests fail. If Community Cloud still
cannot start after the verified dependency update, preserve the private source
release and move the showcase to an isolated deployment entry point with a
minimal dependency file; do not weaken password protection or make the source
repository public.
