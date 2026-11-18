#!/usr/bin/env bash
# Requires a built Dockerfile.rai-core image; no robot network is attached.
set -euo pipefail
image=${1:-diagnostic-rai-core:1.1.0-humble}
docker run --rm --network none -e ROS_DOMAIN_ID=173 "$image" inspect |
  python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["ready"] is True; assert value["source_version"] == "official_1.1.0_api"; assert isinstance(value["observations"], list); print("RAI 1.1.0 Humble read-only tool smoke passed; isolated domain, no robot acceptance")'
