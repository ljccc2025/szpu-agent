# -*- coding: utf-8 -*-
"""M11 沙箱执行工具单元测试：黑名单真测 + docker SDK mock 测。"""
import pytest

from app.tools import registry, sandbox


# ---------- 第一重防线：黑名单（纯逻辑，真测） ----------

@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -fr /",
    "sudo rm -rf / --no-preserve-root",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    ":(){ :|:& };:",
    "shutdown -h now",
    "reboot",
    "echo x > /dev/sda",
    "chmod -R 777 /",
])
def test_dangerous_commands_blocked(cmd):
    assert sandbox.check_blocked(cmd) is not None


@pytest.mark.parametrize("cmd", [
    "ls -la /etc",
    "uname -a",
    "cat /etc/os-release",
    "ps aux",
    "df -h",
    "rm /tmp/test.txt",          # 删普通文件不拦
    "mkdir -p /tmp/demo && ls",
    "echo hello > /tmp/out.txt", # 写普通文件不拦
])
def test_safe_commands_pass(cmd):
    assert sandbox.check_blocked(cmd) is None


def test_run_blocked_never_touches_docker(monkeypatch):
    """被拦截的命令绝不能创建容器。"""
    def boom():
        raise AssertionError("blocked 命令不应触达 docker")
    monkeypatch.setattr(sandbox, "_get_client", boom)
    result = sandbox.run("rm -rf /")
    assert result["blocked"] is True
    assert result["exit_code"] == -1
    assert "拦截" in result["stdout"]


# ---------- docker SDK mock ----------

class FakeContainer:
    def __init__(self, logs=b"hello\n", status_code=0, wait_raises=False):
        self._logs = logs
        self._code = status_code
        self._wait_raises = wait_raises
        self.killed = False
        self.removed = False

    def wait(self, timeout=None):
        if self._wait_raises:
            raise TimeoutError("timed out")
        return {"StatusCode": self._code}

    def kill(self):
        self.killed = True

    def logs(self, stdout=True, stderr=True):
        return self._logs

    def remove(self, force=False):
        self.removed = True


class FakeClient:
    def __init__(self, container):
        self._c = container
        self.run_kwargs = None
        outer = self

        class _Containers:
            def run(self, image, cmd, **kwargs):
                outer.run_kwargs = {"image": image, "cmd": cmd, **kwargs}
                return outer._c

        self.containers = _Containers()


def test_run_success(monkeypatch):
    c = FakeContainer(logs=b"Linux sandbox 6.1\n", status_code=0)
    client = FakeClient(c)
    monkeypatch.setattr(sandbox, "_get_client", lambda: client)
    result = sandbox.run("uname -a")
    assert result == {"stdout": "Linux sandbox 6.1\n", "exit_code": 0, "blocked": False}
    assert c.removed is True  # 用完即焚
    # 五重防线参数逐一验证
    kw = client.run_kwargs
    assert kw["network_disabled"] is True
    assert kw["mem_limit"] == "512m"
    assert kw["nano_cpus"] == int(0.5 * 1e9)
    assert kw["cmd"] == ["/bin/sh", "-c", "uname -a"]


def test_run_timeout_kills_container(monkeypatch):
    c = FakeContainer(wait_raises=True)
    monkeypatch.setattr(sandbox, "_get_client", lambda: FakeClient(c))
    result = sandbox.run("sleep 100")
    assert result["blocked"] is False
    assert result["exit_code"] == -1
    assert "超时" in result["stdout"] or "强制终止" in result["stdout"]
    assert c.killed is True
    assert c.removed is True


def test_run_output_truncated(monkeypatch):
    c = FakeContainer(logs=b"x" * 5000)
    monkeypatch.setattr(sandbox, "_get_client", lambda: FakeClient(c))
    result = sandbox.run("yes | head -c 5000")
    assert len(result["stdout"]) < 4200
    assert "截断" in result["stdout"]


# ---------- 工具入口与注册 ----------

def test_run_command_formats_output(monkeypatch):
    monkeypatch.setattr(
        sandbox, "run",
        lambda cmd: {"stdout": "total 0\n", "exit_code": 0, "blocked": False},
    )
    text = sandbox.run_command("ls -la")
    assert "$ ls -la" in text
    assert "total 0" in text
    assert "退出码: 0" in text


def test_run_command_blocked_message(monkeypatch):
    text = sandbox.run_command("rm -rf /")
    assert "⚠️" in text and "拦截" in text


def test_run_command_docker_unavailable(monkeypatch):
    def boom(cmd):
        raise RuntimeError("docker daemon 未运行")
    monkeypatch.setattr(sandbox, "run", boom)
    text = sandbox.run_command("ls")
    assert "沙箱环境异常" in text


def test_registered_in_registry():
    names = [t["function"]["name"] for t in registry.TOOLS]
    assert "run_command" in names
    assert registry.HANDLERS["run_command"] is sandbox.run_command
    schema = next(t for t in registry.TOOLS if t["function"]["name"] == "run_command")
    assert "command" in schema["function"]["parameters"]["properties"]
