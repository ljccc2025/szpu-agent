"""M11 沙箱执行工具：在一次性 Docker 容器中安全执行 Linux 命令。

安全模型（技术文档 M11-Sandbox）：

真正的隔离边界是"一次性容器 + 禁网 + 降权"。黑名单是**教学提示层**，
用于在命令进入容器前向学生解释其危险性，不应被当作安全边界依赖——
长选项、等效命令、编码后的命令都可能绕过正则匹配。

1. 黑名单正则预检（教学提示，非安全边界）
2. 容器完全禁网 network_disabled=True
3. 内存上限 512MB，且禁止用 swap 绕过
4. CPU 上限 0.5 核 + 进程数上限 64
5. 降权运行：nobody 用户、只读根文件系统、丢弃全部 capability、禁止提权
6. 超时强杀 + 容器用完即焚

docker SDK 7.2.x：detach 模式 + wait(timeout) + 手动 remove(force=True)，
比 auto_remove=True 更稳（auto_remove 在读取日志前可能已把容器删掉）。
"""
import re

from app import config

# 选项 token：同时覆盖短选项(-rf)与长选项(--recursive)，
# 只认短选项是原实现被绕过的主要原因。
_OPT = r"(?:-{1,2}[A-Za-z][\w-]*\s+)*"

# 黑名单：命中即拦截，不进入容器（教学提示层，非安全边界）
BLOCKED_PATTERNS = [
    (r"rm\s+" + _OPT + r"/(\s|$)", "删除根目录"),
    (r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f|rm\s+-[a-zA-Z]*f[a-zA-Z]*r", "强制递归删除"),
    (r"rm\s[^|;&]*--recursive\b", "递归删除"),
    (r"\bfind\b[^|;&]*\s-delete\b", "find 批量删除"),
    (r"\bshred\b", "磁盘安全擦除"),
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
        memswap_limit=config.SANDBOX_MEM,  # 防线3：禁止用 swap 绕过内存上限
        nano_cpus=int(config.SANDBOX_CPU * 1e9),  # 防线4：0.5 核
        pids_limit=64,                   # 防线4：防进程泛滥
        user="nobody",                   # 防线5：非 root 运行
        read_only=True,                  # 防线5：根文件系统只读
        cap_drop=["ALL"],                # 防线5：丢弃全部 capability
        security_opt=["no-new-privileges"],  # 防线5：禁止提权
        tmpfs={"/tmp": "rw,size=16m"},   # 只读根下仍保留可写 /tmp 供教学练习
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
