#!/usr/bin/env python3
"""Run an explicitly selected frp component; never changes OS networking or services."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROLES = {"server": "frps", "cloud": "frpc-cloud", "daq": "frpc-daq"}
REQUIRED = {
    "server": ["FRP_AUTH_TOKEN", "FRP_CERT_FILE", "FRP_KEY_FILE"],
    "cloud": ["FRP_AUTH_TOKEN", "FRP_HUB_SECRET", "FRP_AUTHORITY_SECRET", "FRP_SERVER_ADDR", "FRP_TLS_SERVER_NAME", "FRP_CA_FILE", "HUB_INTERNAL_HOST", "CLOUD_PRIVATE_BIND_IP"],
    "daq": ["FRP_AUTH_TOKEN", "FRP_HUB_SECRET", "FRP_AUTHORITY_SECRET", "FRP_SERVER_ADDR", "FRP_TLS_SERVER_NAME", "FRP_CA_FILE", "DAQ_LAN_IP"],
}

def main(argv=None):
    parser = argparse.ArgumentParser(description="frp专用连接：默认只检查，不自动安装或修改网络")
    parser.add_argument("role", choices=ROLES)
    parser.add_argument("--run", action="store_true", help="明确启动前台进程，Ctrl+C停止")
    parser.add_argument("--bin-dir", type=Path, default=Path(__file__).resolve().parent / "bin")
    args = parser.parse_args(argv)
    missing = [key for key in REQUIRED[args.role] if not os.environ.get(key)]
    if missing:
        print("缺少配置：" + "、".join(missing), file=sys.stderr)
        return 2
    import ipaddress
    for name in ["CLOUD_PRIVATE_BIND_IP"] if args.role == "cloud" else ["DAQ_LAN_IP"] if args.role == "daq" else []:
        try:
            address = ipaddress.ip_address(os.environ[name])
            if not address.is_private or address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast:
                raise ValueError()
        except ValueError:
            print(name + "须填写指定私网网卡地址", file=sys.stderr)
            return 2
    for key in ["FRP_CERT_FILE", "FRP_KEY_FILE"] if args.role == "server" else ["FRP_CA_FILE"]:
        if not Path(os.environ[key]).is_file():
            print("证书文件不存在：" + key, file=sys.stderr)
            return 2
    executable = args.bin_dir / ("frps" if args.role == "server" else "frpc")
    config = Path(__file__).resolve().parent / "templates" / (ROLES[args.role] + ".toml.example")
    if not executable.is_file():
        print("请放置已校验的frp v0.72.0可执行文件", file=sys.stderr)
        return 2
    result = subprocess.run([str(executable), "verify", "-c", str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        print("配置检查失败；请核对字段、证书与官方版本", file=sys.stderr)
        return result.returncode
    if not args.run:
        print("配置检查通过；未启动服务，未修改电脑配置")
        return 0
    child = subprocess.Popen([str(executable), "-c", str(config)])
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            return child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            return 130

if __name__ == "__main__":
    raise SystemExit(main())
