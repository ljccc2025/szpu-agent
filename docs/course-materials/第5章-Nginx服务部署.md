# 第5章 Nginx 服务部署

《Linux 系统管理与运维》课程讲义 · 深圳职业技术大学

## 5.1 Nginx 简介与安装

Nginx 是一款高性能的 HTTP 服务器和反向代理服务器，采用事件驱动的异步非阻塞架构，能够以较低的内存占用支撑高并发连接。在生产环境中，Nginx 常用于静态资源服务、反向代理、负载均衡与 HTTPS 终结。

在 Rocky Linux / CentOS 系统中，使用 dnf 包管理器安装：

```bash
dnf install -y nginx        # 安装
systemctl enable --now nginx  # 设置开机自启并立即启动
systemctl status nginx      # 查看运行状态
```

安装完成后，主配置文件位于 /etc/nginx/nginx.conf，站点配置通常放在 /etc/nginx/conf.d/ 目录下，默认网站根目录为 /usr/share/nginx/html。

## 5.2 静态网站配置

一个最小的静态站点 server 块配置如下：

```nginx
server {
    listen 80;
    server_name www.szpu-lab.cn;
    root /var/www/site;
    index index.html;
}
```

要点：listen 指定监听端口；server_name 用于基于域名的虚拟主机匹配；root 指定站点根目录。修改配置后需要重载服务才能生效。

## 5.3 反向代理配置

反向代理是 Nginx 最重要的应用场景之一。反向代理服务器接收客户端请求后，通过 proxy_pass 指令将请求转发至后端真实服务器，客户端并不感知后端的存在。标准配置如下：

```nginx
server {
    listen 80;
    server_name www.szpu-lab.cn;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

期末考点提示：

1. proxy_pass 末尾是否带斜杠 / 会影响路径拼接结果。带 / 时，location 匹配的前缀部分会被替换掉；不带 / 时，原始 URI 会完整拼接到目标地址后。
2. proxy_set_header Host $host 保证后端应用拿到原始域名。
3. 通过 proxy_set_header 传递 X-Real-IP，便于后端应用获取客户端真实地址，否则后端日志中记录的客户端地址将全部是 127.0.0.1。

## 5.4 常见配置错误与排查

修改配置文件后必须执行 nginx -t 进行语法检测，通过后使用 systemctl reload nginx 平滑重载，避免直接 restart 造成连接中断：

```bash
nginx -t                    # 语法检测:出错时会给出具体行号
systemctl reload nginx      # 平滑重载:老连接继续服务,新连接用新配置
```

reload 与 restart 的区别：reload 只重新加载配置文件，主进程不退出，正在处理的连接不受影响；restart 会先停止再启动整个服务，期间所有连接中断。生产环境应优先使用 reload。

常见错误排查思路：

1. 配置语法错误：nginx -t 输出会给出出错文件与行号，按提示修改。
2. 端口被占用：使用 ss -tlnp | grep :80 查看占用进程。
3. SELinux 拦截：反向代理到非标准端口时需执行 setsebool -P httpd_can_network_connect 1。
4. 防火墙未放行：firewall-cmd --permanent --add-service=http && firewall-cmd --reload。

## 5.5 负载均衡基础

通过 upstream 块定义后端服务器组，实现负载均衡：

```nginx
upstream backend {
    server 192.168.100.11:8080 weight=2;
    server 192.168.100.12:8080;
    server 192.168.100.13:8080 backup;
}

server {
    listen 80;
    location / {
        proxy_pass http://backend;
    }
}
```

调度策略：默认轮询；weight 设置权重；ip_hash 实现会话保持；backup 标记备用节点，仅当所有主节点失效时启用。
