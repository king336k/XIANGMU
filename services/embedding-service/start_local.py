"""Check a portable local service; only --apply creates a missing container."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets

import docker


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-name", default=os.environ.get("EMBEDDING_SERVICE_NAME", "engramproject-embedding"))
    parser.add_argument("--network", default=os.environ.get("EMBEDDING_DOCKER_NETWORK", "engramproject_default"))
    parser.add_argument("--model-dir", default=os.environ.get("EMBEDDING_MODEL_DIR"))
    parser.add_argument("--image", default=os.environ.get("EMBEDDING_IMAGE", "engramproject/embedding:bge-small-zh-v1.5"))
    parser.add_argument("--host-port", type=int, default=os.environ.get("EMBEDDING_HOST_PORT", "18885"))
    parser.add_argument("--no-publish", action="store_true", help="Use Docker network DNS only; publish no host port")
    parser.add_argument("--apply", action="store_true", help="Create a missing service; never replace an existing container")
    return parser.parse_args(argv)


def main(argv=None):
    args = arguments(argv)
    client = None
    try:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", args.service_name):
            raise ValueError("service name must be a DNS label")
        if args.network in {"bridge", "host", "none"} or not args.network:
            raise ValueError("select an existing user-defined Docker network")
        if not 1 <= args.host_port <= 65535:
            raise ValueError("host port must be 1..65535")
        if not args.model_dir:
            raise ValueError("provide --model-dir or EMBEDDING_MODEL_DIR")
        root = Path(args.model_dir).expanduser().resolve(strict=True)
        if not all((root / name).is_file() for name in ("model.onnx", "tokenizer.json")):
            raise ValueError("model directory must contain model.onnx and tokenizer.json")
        client = docker.from_env()
        client.networks.get(args.network)
        try:
            container = client.containers.get(args.service_name)
            if args.network not in container.attrs["NetworkSettings"]["Networks"]:
                raise ValueError("existing service is preserved but does not share the selected network")
            result = {"applied": False, "existing_service_preserved": True, "status": str(container.status)}
        except docker.errors.NotFound:
            client.images.get(args.image)
            result = {"applied": False, "existing_service_preserved": False}
            if args.apply:
                client.containers.run(
                    args.image, name=args.service_name, hostname=args.service_name, detach=True,
                    network=args.network, ports={} if args.no_publish else {"18885/tcp": ("127.0.0.1", args.host_port)},
                    environment={"EMBEDDING_API_KEY": secrets.token_urlsafe(40), "MODEL_DIR": "/model"},
                    volumes={str(root): {"bind": "/model", "mode": "ro"}},
                    read_only=True, cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
                    mem_limit="1g", memswap_limit="1g", nano_cpus=2_000_000_000, pids_limit=128,
                    restart_policy={"Name": "unless-stopped"},
                    healthcheck={"test": ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:18885/health',timeout=3)"], "interval": 30_000_000_000, "timeout": 5_000_000_000, "start_period": 10_000_000_000, "retries": 3},
                )
                result["applied"] = True
        result.update(service=args.service_name, network=args.network,
                      local_endpoint=None if args.no_publish else f"http://127.0.0.1:{args.host_port}/v1",
                      internal_endpoint=f"http://{args.service_name}:18885/v1")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ValueError as error:
        print(json.dumps({"error": str(error), "applied": False}))
        return 1
    except Exception:
        # Docker errors may include a request body containing the generated key.
        print(json.dumps({"error": "Docker/model preflight or creation failed; sensitive details suppressed"}))
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
