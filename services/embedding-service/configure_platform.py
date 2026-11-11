"""Verify a shared-network embedding service; --apply writes encrypted settings atomically."""
import argparse
import json
import os
import re
import subprocess

import docker


PLATFORM_PROGRAM = r'''
import os,json,sys,hashlib
from contextlib import nullcontext
os.environ.setdefault("DJANGO_SETTINGS_MODULE","plane.settings.production")
import django;django.setup()
from django.db import transaction
from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import encrypt_data
from plane.knowledge import assistant,semantic_provider
values=json.load(sys.stdin)
if not semantic_provider.valid_embedding_url(values['base_url']):
 raise RuntimeError("Embedding origin must be explicitly allowed on the platform")
fingerprint=lambda row:hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
with transaction.atomic() if values['apply'] else nullcontext():
 original=fingerprint(assistant.provider_config())
 if values['apply']:
  for key,value,secret in [("KNOWLEDGE_EMBEDDING_BASE_URL",values["base_url"],False),("KNOWLEDGE_EMBEDDING_MODEL",values["model"],False),("KNOWLEDGE_EMBEDDING_API_KEY",values["api_key"],True),("KNOWLEDGE_SEMANTIC_ENABLED","true",False)]:
   if secret:
    value=encrypt_data(value)
    if not value: raise RuntimeError("Encryption unavailable")
   InstanceConfiguration.objects.update_or_create(key=key,defaults={"value":value,"is_encrypted":secret,"category":"KNOWLEDGE"})
  current=semantic_provider.configuration()
 else:
  current={**values,'enabled':True,'configured':True}
 if not current['configured'] or current['base_url']!=values['base_url'] or current['model']!=values['model']:
  raise RuntimeError("Embedding configuration verification failed")
 vectors=semantic_provider.embed(['设备无法连接，服务端没有监听端口。','采集数据存储目录没有可写权限。'],current)
 if len(vectors)!=2 or any(len(row)!=512 for row in vectors):
  raise RuntimeError("Embedding shape verification failed")
 if fingerprint(assistant.provider_config())!=original:
  raise RuntimeError("Chat configuration changed")
print(json.dumps({"applied":values['apply'],"verified":True,"model":current["model"],"base_url":current["base_url"],"dimensions":512,"test_vectors":2,"chat_configuration_unchanged":True},ensure_ascii=False))
'''


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-name", default=os.environ.get("EMBEDDING_SERVICE_NAME", "engramproject-embedding"))
    parser.add_argument("--network", default=os.environ.get("EMBEDDING_DOCKER_NETWORK", "engramproject_default"))
    parser.add_argument("--api-container", default=os.environ.get("PLATFORM_API_CONTAINER"))
    parser.add_argument("--apply", action="store_true", help="Write only embedding settings, rolling back if verification fails")
    return parser.parse_args(argv)


def main(argv=None):
    args = arguments(argv)
    client = None
    try:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", args.service_name):
            raise ValueError("service name must be a DNS label")
        if not args.api_container:
            raise ValueError("provide --api-container or PLATFORM_API_CONTAINER")
        if args.network in {"bridge", "host", "none"} or not args.network:
            raise ValueError("select an existing user-defined Docker network")
        client = docker.from_env()
        service = client.containers.get(args.service_name)
        api = client.containers.get(args.api_container)
        if any(args.network not in container.attrs["NetworkSettings"]["Networks"] for container in [service, api]):
            raise ValueError("service and API container must share the selected network")
        environment = dict(row.split("=", 1) for row in service.attrs["Config"]["Env"] if "=" in row)
        key = environment.get("EMBEDDING_API_KEY", "")
        if not key:
            raise ValueError("embedding service key is missing")
        values = {"base_url": f"http://{args.service_name}:18885/v1", "api_key": key,
                  "model": "bge-small-zh-v1.5", "apply": args.apply}
        result = subprocess.run(
            ["docker", "exec", "-i", "-w", "/code", args.api_container, "python", "-c", PLATFORM_PROGRAM],
            input=json.dumps(values), capture_output=True, text=True, timeout=90,
        )
        if result.returncode:
            raise RuntimeError("Platform verification failed; check the allowed embedding origin, connectivity and encryption")
        receipt = json.loads(result.stdout)
        # Only known public fields are printed; subprocess diagnostics may contain credentials.
        fields = ["applied", "verified", "model", "base_url", "dimensions", "test_vectors", "chat_configuration_unchanged"]
        print(json.dumps({name: receipt[name] for name in fields}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error) if not isinstance(error, json.JSONDecodeError) else "Platform receipt unavailable"}))
        return 1
    except Exception:
        print(json.dumps({"error": "Docker/platform verification failed; sensitive details suppressed"}))
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
