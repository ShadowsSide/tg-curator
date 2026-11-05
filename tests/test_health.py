"""容器健康检查（bot/health.py）。用法：python tests/test_health.py

- 有配置错误文件：不健康，输出里是错误说明
- 心跳文件不存在（还在启动）或刚更新过：健康
- 心跳太久没更新：不健康，说明按 LANGUAGE 显示
- Dockerfile 的 HEALTHCHECK 调用的就是它，并且真的能在命令行跑起来
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))

from bot import health  # noqa: E402


def paths(d):
    return os.path.join(d, "config-error"), os.path.join(d, "heartbeat")


def touch(path, age=0.0):
    pathlib.Path(path).touch()
    when = time.time() - age
    os.utime(path, (when, when))


def test_config_error_is_unhealthy():
    with tempfile.TemporaryDirectory() as d:
        err, beat = paths(d)
        pathlib.Path(err).write_text("配置错误：没有填写 CHANNEL_ID\n", encoding="utf-8")
        touch(beat)
        assert health.check(err, beat) == "配置错误：没有填写 CHANNEL_ID"


def test_starting_and_fresh_heartbeat_are_healthy():
    with tempfile.TemporaryDirectory() as d:
        err, beat = paths(d)
        assert health.check(err, beat) is None  # 还没写心跳：在启动
        touch(beat, age=health.HEARTBEAT_MAX_AGE - 30)
        assert health.check(err, beat) is None


def test_stale_heartbeat_is_unhealthy():
    old = os.environ.get("LANGUAGE")
    try:
        with tempfile.TemporaryDirectory() as d:
            err, beat = paths(d)
            touch(beat, age=health.HEARTBEAT_MAX_AGE + 60)
            os.environ["LANGUAGE"] = "zh"
            got = health.check(err, beat)
            assert got and "没有响应" in got and str(health.HEARTBEAT_MAX_AGE + 60) in got, got
            os.environ["LANGUAGE"] = "en"
            assert "hasn't responded" in health.check(err, beat)
    finally:
        os.environ.pop("LANGUAGE", None) if old is None else os.environ.update(LANGUAGE=old)


def run_cli(env):
    return subprocess.run([sys.executable, "-m", "bot.health"], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, **env}, timeout=30)


def test_cli_exit_codes():
    with tempfile.TemporaryDirectory() as d:
        err, beat = paths(d)
        env = {"CONFIG_ERROR_FILE": err, "HEARTBEAT_FILE": beat, "LANGUAGE": "en"}
        touch(beat)
        assert run_cli(env).returncode == 0
        touch(beat, age=health.HEARTBEAT_MAX_AGE + 60)
        r = run_cli(env)
        assert r.returncode == 1 and "hasn't responded" in r.stdout, (r.returncode, r.stdout, r.stderr)
        pathlib.Path(err).write_text("Configuration error: x\n", encoding="utf-8")
        r = run_cli(env)
        assert r.returncode == 1 and r.stdout.strip() == "Configuration error: x", r.stdout


def test_dockerfile_uses_it():
    text = (ROOT / "Dockerfile").read_text()
    assert 'CMD ["python", "-m", "bot.health"]' in text and "HEALTHCHECK" in text, text
    assert "/tmp/config-error" not in text  # 文件位置只在 bot/health.py 里定义


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
