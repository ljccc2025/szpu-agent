"""M11 沙箱执行工具：在一次性 Docker 容器中安全执行 Linux 命令。

五重防线（技术文档 M11-Sandbox）：
1. 黑名单正则预检（危险命令不进容器）
2. 容器完全禁网 network_disabled=True
3. 内存上限 512MB
4. CPU 上限 0.5 核
5. 超时强杀 + 容器用完即焚

docker SDK 7.2.x：detach 模式 + wait(timeout) + 手动 remove(force=True)，
比 auto_remove=True 更稳（auto_remove 在读取日志前可能已把容器删掉）。
"""
import re

from app import config

# 黑名单：命中即拦截，不进入容器（第一重防线，也是教学点）
BLOCKED_PATTERNS = [
    (r"rm\s+(-[a-zA-Z]*\s+)*/(\s|$)", "删除根目录"),
    (r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f|rm\s+-[a-zA-Z]*f[a-zA-Z]*r", "强制递归删除"),
    (r"mkfs", "格式化文件系统"),
    (r"dd\s+if=", "磁盘底层写入"),
    (r":\s*\(\s*\)\s*\{.*\}\s*;\s*:", "fork 炸弹"),
    (r"\bshutdown\b|\breboot\b|\bpoweroff\b|\bhalt\b", "关闭/重启系统"),
    (r">\s*/dev/sd|>\s*/dev/vd|>\s*/dev/nvme", "覆写磁盘设备"),
    (r"chmod\s+(-[a-zA-Z]*\s+)*777\s+/(\s|$)", "根目录权限破坏"),
]

_client = None


def check_blocked(cmd: str):
    """返回命中的危险原因；安全则返回 None。"""
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, cmd):
            return reason
    return None


def _get_client():
    """docker client 单例懒加载：不装 docker SDK 也能 import 本模块（便于测试）。"""
    global _client
    if _client is None:
        import docker

        _client = docker.from_env()
    return _client


def run(cmd: str) -> dict:
    """执行命令，返回 {stdout, exit_code, blocked}（技术文档 M11 对外 API）。"""
    reason = check_blocked(cmd)
    if reason:
        return {
            "stdout": f"命令被安全策略拦截（{reason}）。该命令具有破坏性，禁止在任何环境随意执行。",
            "exit_code": -1,
            "blocked": True,
        }

    client = _get_client()
    container = client.containers.run(
        config.SANDBOX_IMAGE,
        ["/bin/sh", "-c", cmd],
        detach=True,
        network_disabled=True,           # 防线2：禁网
        mem_limit=config.SANDBOX_MEM,    # 防线3：内存 512m
        nano_cpus=int(config.SANDBOX_CPU * 1e9),  # 防线4：0.5 核
        pids_limit=64,                   # 加固：防进程泛滥
    )
    try:
        try:
            result = container.wait(timeout=config.SANDBOX_TIMEOUT)  # 防线5：超时
            exit_code = result.get("StatusCode", -1)
        except Exception:
            container.kill()
            return {
                "stdout": f"命令执行超过 {config.SANDBOX_TIMEOUT} 秒被强制终止（沙箱超时保护）。",
                "exit_code": -1,
                "blocked": False,
            }
        output = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
        if len(output) > 4000:
            output = output[:4000] + "\n...（输出过长已截断）"
        return {"stdout": output, "exit_code": exit_code, "blocked": False}
    finally:
        try:
            container.remove(force=True)  # 用完即焚
        except Exception:
            pass


def run_command(command: str) -> str:
    """工具入口（registry 调用）：把 run() 结果格式化为给 LLM 的文本。"""
    try:
        result = run(command)
    except Exception as err:
        return f"沙箱环境异常，命令未执行：{err}"
    if result["blocked"]:
        return f"⚠️ {result['stdout']}"
    return (
        f"$ {command}\n{result['stdout'].rstrip()}\n[退出码: {result['exit_code']}]"
    )
