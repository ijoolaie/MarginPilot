"""Resolve + verify Docker base-image tags via the Docker Registry HTTP API.

No Docker daemon is needed: token auth + manifest HEAD gives the
Docker-Content-Digest for each tag, which both proves the tag EXISTS and
yields the digest for reproducible pins in docker-compose.yml.

Sandbox-only verification tool — not a product dependency.
"""

import hashlib
import json
import sys
import urllib.request

AUTH = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
REGISTRY = "https://registry-1.docker.io/v2/{repo}/manifests/{tag}"

IMAGES = [
    ("library/python", "3.12-slim-bookworm"),
    ("library/node", "24-alpine"),
    ("nginxinc/nginx-unprivileged", "1.29-alpine"),
    ("library/postgres", "16-alpine"),
    ("library/caddy", "2-alpine"),
]

ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    ]
)


def fetch(url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return body, dict(response.headers)


def resolve(repo: str, tag: str) -> dict[str, str]:
    token_url = AUTH.format(repo=repo)
    body, _headers = fetch(token_url, {"Accept": "application/json"})
    token = json.loads(body.decode())["token"]

    manifest_url = REGISTRY.format(repo=repo, tag=tag)
    body, headers = fetch(
        manifest_url,
        {"Authorization": f"Bearer {token}", "Accept": ACCEPT},
    )
    # The registry digest is exactly sha256(raw manifest bytes).
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    content_type = headers.get("Content-Type", "")
    return {"repo": repo, "tag": tag, "digest": digest, "media_type": content_type}


def main() -> None:
    results = []
    failed = False
    for repo, tag in IMAGES:
        try:
            entry = resolve(repo, tag)
        except Exception as exc:  # noqa: BLE001 — evidence output, not app code
            entry = {"repo": repo, "tag": tag, "error": f"{type(exc).__name__}: {exc}"}
            failed = True
        results.append(entry)
        print(entry)
    with open("/home/z/my-project/download/evidence/image_digests.json", "w") as fh:
        json.dump(results, fh, indent=2)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
