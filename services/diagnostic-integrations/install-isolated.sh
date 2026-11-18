#!/usr/bin/env bash
# Explicit installation helper; never called automatically by diagnosis.
set -euo pipefail
role=${1:?usage: install-isolated.sh central|rosa|holmes|rai-core|rai INSTALL_ROOT}
target=${2:?provide an absolute install root}
case "$target" in /*) ;; *) echo 'absolute install root required' >&2; exit 2;; esac
sources=$(cd -- "$(dirname -- "$0")" && pwd)
task_python=${DIAGNOSTIC_INTEGRATION_PYTHON:-/usr/bin/python3}
case "$role" in
  central|rosa|holmes)
    if [[ "$role" == rosa ]]; then
      [[ "${ROS_DISTRO:-}" == humble ]] || { echo 'source ROS Humble before installation' >&2; exit 2; }
      "$task_python" -c 'import rclpy'
      "$task_python" -m venv --system-site-packages "$target/$role"
    else
      "$task_python" -m venv "$target/$role"
    fi
    "$target/$role/bin/python" -m pip install -r "$sources/requirements-$role.txt"
    "$target/$role/bin/python" -m pip check
    ;;
  rai|rai-core)
    [[ "${ROS_DISTRO:-}" == humble || "${ROS_DISTRO:-}" == jazzy ]] || { echo 'source ROS Humble or Jazzy before installing official RAI 1.1.0' >&2; exit 2; }
    mkdir -p "$target"
    git clone https://github.com/RobotecAI/rai.git "$target/rai-source"
    git -C "$target/rai-source" checkout --detach 9564f4fb5fc23e78418070a80f8ac652382e1f29
    "$task_python" -c 'import rclpy'
    "$task_python" -m venv --system-site-packages "$target/rai"
    if [[ "$role" == rai-core ]]; then
      "$task_python" -c 'import cv_bridge, tf_transformations'
      "$target/rai/bin/python" -m pip install -r "$sources/requirements-rai-core.txt"
      "$target/rai/bin/python" -m pip install --no-deps "$target/rai-source/src/rai"
      "$target/rai/bin/python" -m pip check
    else
      command -v colcon >/dev/null
      "$task_python" -m venv "$target/rai-tools"
      "$target/rai-tools/bin/python" -m pip install poetry==1.8.5
      (cd "$target/rai-source" && VIRTUAL_ENV="$target/rai" PATH="$target/rai/bin:$PATH" "$target/rai-tools/bin/poetry" install --only main --no-root --sync)
      (cd "$target/rai-source" && VIRTUAL_ENV="$target/rai" PATH="$target/rai/bin:$PATH" colcon build --symlink-install)
      echo "Before bridge execution source $target/rai-source/install/setup.bash and activate $target/rai/bin/activate"
    fi
    ;;
  *) echo 'unknown role' >&2; exit 2;;
esac
cp "$sources/specialist.py" "$target/specialist.py"
cp "$sources/holmes_runner.py" "$target/holmes_runner.py"
cp "$sources/holmes-toolsets.yaml" "$target/holmes-toolsets.yaml"
