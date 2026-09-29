# 第10章 容器与 Kubernetes 运维

《Linux 系统管理与运维》课程讲义 · 深圳职业技术大学

## 10.1 核心概念

- **容器与虚拟机的本质区别**：容器共享宿主机内核，靠 Namespace 隔离视图、Cgroup 限制资源，启动秒级；虚拟机各带完整内核，隔离更强但开销大。
- **Pod**：Kubernetes 最小调度单元，一个 Pod 内的容器共享网络与存储卷；Pod 是"牲口不是宠物"，随时可能被杀掉重建。
- **声明式控制循环**：用户提交期望状态（如副本数 3），控制器持续比对实际状态并自动收敛，节点挂掉后 Pod 自动在别处重建。
- **Service 与 Ingress**：Service 为一组 Pod 提供稳定虚拟 IP 与负载均衡；Ingress 负责七层路由，把外部 HTTP 流量按域名/路径转发到不同 Service。

## 10.2 关键知识点

1. 核心工作负载对象：Deployment（无状态服务）、StatefulSet（有状态服务，稳定网络标识与存储）、DaemonSet（每节点一份，如日志采集器）、Job/CronJob（一次性与定时任务）。
2. 三种健康探针：liveness（存活探针，失败则重启容器）、readiness（就绪探针，失败则摘除流量）、startup（启动探针，保护慢启动应用）。就绪探针配置不当是"发布抖动"的常见原因。
3. 资源管理：requests 决定调度（节点须有此余量）、limits 决定上限（CPU 超限被限流、内存超限触发 OOMKilled）。requests 与 limits 差距过大将导致节点超卖不稳定。
4. QoS 等级：Guaranteed（requests=limits）> Burstable > BestEffort，节点内存吃紧时按此顺序反向驱逐。
5. 排障命令链：`kubectl get pod -o wide` 看状态 → `kubectl describe pod` 看事件（镜像拉取失败、调度失败原因在这里）→ `kubectl logs --previous` 看崩溃前日志 → `kubectl exec -it` 进容器现场排查。
6. 常见 Pod 异常状态：ImagePullBackOff（镜像名错误或仓库凭据缺失）、CrashLoopBackOff（进程反复崩溃，查上一次日志）、Pending（资源不足或亲和性无法满足）、OOMKilled（内存超 limit）。
7. HPA 自动扩缩容：基于 CPU/内存或自定义指标（如 QPS）自动调整副本数，需配合 requests 设置合理才能生效。
8. 镜像最佳实践：多阶段构建减小体积、固定标签禁用 latest、非 root 用户运行。

## 10.3 常用工具与技术栈

| 工具 | 用途 |
|------|------|
| kubectl | 集群操作与排障的第一工具 |
| Helm | 应用打包与版本化发布（Chart） |
| containerd | 主流容器运行时（Docker 已被弃用为运行时） |
| k9s | 终端可视化集群管理，排障效率倍增 |
| kube-prometheus-stack | 集群监控标配套件 |

## 10.4 典型实践场景与最佳实践

### 场景一：CrashLoopBackOff 十分钟定位法
`kubectl describe pod` 确认重启原因与退出码 → 退出码 137 说明 OOMKilled，调大 limits 或查内存泄漏；其他退出码执行 `kubectl logs --previous` 查崩溃前最后日志，多数是配置缺失或依赖连不上。

### 场景二：生产级 Deployment 检查清单
上线前确认：readiness/liveness 探针已配置且阈值合理、requests/limits 已按压测结果设置、副本数≥2 且配置 PodDisruptionBudget、滚动更新参数 maxUnavailable 不为 100%、镜像使用固定版本标签。
