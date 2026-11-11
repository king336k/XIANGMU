#!/usr/bin/env python3
"""Credential-free distribution: set runtime identity in environment, never save secrets to config."""

import argparse
import ipaddress
import json
import os
import shutil
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def clean(value):
    if isinstance(value, dict):
        return {
            key: clean(item)
            for key, item in value.items()
            if not any(
                word in key.lower().replace("_", "")
                for word in ["password", "secret", "token", "apikey", "credential", "authorization", "cookie"]
            )
        }
    if isinstance(value, list):
        return [clean(item) for item in value[:50]]
    return value


def snapshot(args):
    disk = shutil.disk_usage(args.workdir)
    data = {
        "device": args.device,
        "performance": {
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        },
        "daq": {"status": "not_checked"},
    }
    if args.daq_url:
        parsed = urlsplit(args.daq_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username
            or parsed.password
        ):
            raise ValueError("DAQ URL must be an explicit loopback endpoint without credentials")
        headers = {"Accept": "application/json"}
        token = os.environ.get("DAQ_RUNTIME_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        with build_opener(NoRedirect).open(Request(args.daq_url, headers=headers), timeout=5) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("DAQ status response too large")
        data["daq"] = {"status": "observed", "snapshot": clean(json.loads(raw))}
    return data


def send(args):
    origin = args.server.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Server must be an origin without credentials")
    if parsed.scheme != "https":
        private = parsed.hostname == "localhost"
        try:
            private = private or ipaddress.ip_address(parsed.hostname).is_private
        except ValueError:
            pass
        if parsed.scheme != "http" or not args.allow_private_http or not private:
            raise ValueError("HTTPS required unless private HTTP explicitly enabled")
    path = f"/api/workspaces/{args.workspace}/projects/{args.project}/quality/field-agents/{args.agent}/heartbeat/"
    body = json.dumps(
        {"request_id": str(uuid.uuid4()), "snapshot": snapshot(args)}, ensure_ascii=False, separators=(",", ":")
    ).encode()
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("FIELD_AGENT_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    elif os.environ.get("PLANE_RUNTIME_COOKIE"):
        headers["Cookie"] = os.environ["PLANE_RUNTIME_COOKIE"]
    else:
        raise ValueError(
            "Provide per-resource FIELD_AGENT_TOKEN through environment; this client never stores credentials"
        )
    with build_opener(NoRedirect).open(Request(origin + path, data=body, headers=headers), timeout=10) as response:
        if response.status not in {200, 201}:
            raise ValueError("Snapshot was not accepted")
    print("Snapshot accepted as observation; not a test verdict", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Native project hub field observation client")
    for key in ["server", "workspace", "project", "agent", "device"]:
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--daq-url")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--allow-private-http", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    # IDs and workspace are path components, never arbitrary paths.
    uuid.UUID(args.project)
    uuid.UUID(args.agent)
    if not args.workspace or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in args.workspace
    ):
        raise ValueError("Invalid workspace slug")
    while True:
        try:
            send(args)
        except Exception as error:
            print("Heartbeat failed: " + type(error).__name__, flush=True)
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(max(10, min(args.interval, 300)))


if __name__ == "__main__":
    main()
