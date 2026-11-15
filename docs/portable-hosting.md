# Presentation hosting

The portable host serves the built Leaflet atlas, static GLOF studies and all
existing Python API routes from one origin. It uses Gunicorn and Flask; model
weights and scientific outputs are unchanged. The Vercel deployment remains
available separately.

## Docker / Render

```sh
docker build -t terrapulse .
docker run --rm -p 8080:8080 terrapulse
```

For Render, connect this repository as a Docker web service and set the health
check path to `/healthz`. The image binds to the host-provided `PORT`. Free
Render services sleep when idle; account setup and memory validation are still
needed before using that option for a presentation.

## Existing server

The current presentation deployment uses a dedicated user-owned directory,
an isolated Python environment, Gunicorn on loopback port 8089, and an outbound
Cloudflare Quick Tunnel. It needs no firewall change, root access or paid plan.
The shared server's other services and datasets are not changed.

Run from a release containing `dist`, `api`, `deployment` and `server_data`:

```sh
python3 -m venv venv
venv/bin/pip install -r requirements-hosting.txt
venv/bin/gunicorn --bind 127.0.0.1:8089 --workers 1 --threads 4 --timeout 60 deployment.gateway:app
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8089
```

Quick Tunnel URLs are temporary. They last while the tunnel process runs and
change when a new tunnel is created; Cloudflare provides no uptime guarantee.
Use a named tunnel/domain or a managed host for long-term publication.

Vercel runtime OIDC credentials do not move to this host. Deterministic chat
commands and source-grounded canned explanations work without credentials.
Optional generative chat needs a server-side `GROQ_API_KEY`,
`AI_GATEWAY_API_KEY`, or the existing `TERRAPULSE_CHAT_*` configuration.
Never put these keys in the frontend, repository, deployment archive or logs.

Public OSM and NASA services can still time out. Cached evidence is labelled;
missing upstream data never becomes a zero-exposure or safety conclusion.

## Validation

```sh
python -m unittest discover -s deployment/tests -v
python -m unittest discover -s api/tests -v
```

Gateway tests include a real ONNX example, GLOF geometry/CSV, chat actions,
response headers, request-size limits, and refusal to expose repository files.
The Docker CI job runs these contracts inside the built image.
