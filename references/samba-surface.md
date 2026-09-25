# Samba / SMB 探测结论（脱敏）

在局域网内对小米智能存储（MINAS）做只读探测后的结论。**不含真实 IP、账号、密码。**

## 服务

| 项 | 结论 |
|---|---|
| 端口 | 445（SMB）、139（NetBIOS）开放 |
| 协议 | 可见 SMB 3.1.1 |
| 主机名 | 设备公告名为 `MINAS`（以实际 `net view` 为准） |

## 共享

- `net view \\<NAS>` 可列出已发布的共享
- 实测可见的共享名形如：`<用途>-<用户数字>`（例如网盘类分享目录）
- 中文共享名在 `net view` 里可能显示乱码，但 UNC 路径可直接使用**资源管理器中的原名**
- 并非 `/pool0/data` 全盘都会自动共享；**以官方客户端里开启的 Samba 共享为准**

## 认证

| 模式 | 结果 |
|---|---|
| 当前 Windows 用户已有会话 | 可直接访问 UNC |
| 指定 `/user:xxx` 再连 | 可用；但同一主机混用多套凭据会触发 **1219** |
| 仅 guest | 未验证通过 |

### 1219 处理

```text
Multiple connections to a server ... more than one user name ...
```

处理：`net use * /delete /y` 后再用同一套凭据访问。

## 文件操作

| 操作 | 方式 |
|---|---|
| 列表 | 直接读 UNC 目录（`pathlib` / 资源管理器） |
| 复制 | `shutil.copy2` / `robocopy` |
| 删除 | 文件系统删除（需权限） |
| 容量 | `shutil.disk_usage`（共享根） |

## 与 WebDAV 的差异（供对照）

| 项 | Samba | WebDAV（此设备） |
|---|---|---|
| 端口 | 445 | 5000 |
| 根路径 | `\\host\share` | `/pool0/data` 等 |
| 远程访问 | 一般仅内网 | 可结合官方远程 |
| Agent 默认 | **本 Skill 采用** | 旧方案 |

## 建议

1. 在官方客户端把需要的目录做成 Samba 共享  
2. Agent 只碰明确共享出来的目录  
3. 大批量整理先 `get` 到本地再 `put` 回去
