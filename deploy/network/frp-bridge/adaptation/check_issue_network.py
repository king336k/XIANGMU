#!/usr/bin/env python3
"""Read-only connectivity precheck for direct LAN and optional project-platform tunnel."""
import argparse
import json
import socket
from urllib.parse import urlsplit


def target(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("请填写不含凭据的HTTP(S)服务地址")
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读检查DAQ与数据平台/项目平台端口，不修改网络配置")
    parser.add_argument("--data-platform", type=target, required=True)
    parser.add_argument("--project-platform", type=target)
    parser.add_argument("--tunnel-server", type=target)
    args = parser.parse_args(argv)
    results = []
    for label, endpoint in [("数据平台", args.data_platform), ("项目平台", args.project_platform), ("可选专用通道", args.tunnel_server)]:
        if endpoint is None:
            continue
        try:
            with socket.create_connection(endpoint, timeout=3):
                reachable = True
        except OSError:
            reachable = False
        results.append({"服务": label, "端口可达": reachable})
    print(json.dumps({"checks": results, "业务鉴权已验证": False, "说明": "端口可达不能代替账号、上报和回归业务验收"}, ensure_ascii=False))
    return 0 if all(row["端口可达"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
