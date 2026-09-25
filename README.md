# 小米智能存储 Samba 文件助手 · 使用文档

面向 **Agent / 脚本** 的小米智能存储（Xiaomi Smart Storage，内部代号 MINAS）文件工具。  
通过 **Samba（SMB/CIFS）** 列目录、统计空间、上传下载、整理文件，无需挂载盘符。

> 非小米官方项目。请只在你自己拥有或已授权的设备上使用。

---

## 1. 它能做什么

| 功能 | 命令 |
|---|---|
| 发现共享 | `shares` |
| 列目录 | `ls` |
| 看体积 | `du` / `df` / `tree` |
| 传文件 | `get` / `put` / `cat` |
| 整理 | `mkdir` / `mv` / `cp` / `rm` / `find` |

**不包含**：SSH、root、Docker、固件修改、挂载盘符守护进程。

---

## 2. 环境要求

- Windows 10/11（主路径使用系统 SMB 客户端）
- 小米智能存储与电脑在同一局域网
- 官方客户端里已开启 Samba 共享（能看到 `\\主机\共享名`）
- Python 3.10+（仅用于运行 CLI）

---

## 3. 配置

推荐用环境变量，**不要写进代码或仓库**：

```powershell
$env:MINAS_HOST = "<NAS 的 IP 或主机名>"
$env:MINAS_SHARE = "<共享名>"
# 若 Windows 没有现成会话再设置：
$env:MINAS_USER = "<SMB 用户名>"
$env:MINAS_PASS = "<SMB 密码>"
```

也可以只用当前 Windows 已认证的 SMB 会话（资源管理器能打开共享即可）。

---

## 4. 快速开始

```powershell
# 1. 看有哪些共享
python scripts/minas.py shares --host 192.168.x.x

# 2. 列出共享内容（把 host/share 换成你的）
python scripts/minas.py ls //192.168.x.x/共享名

# 3. JSON 输出（给程序用）
python scripts/minas.py ls //192.168.x.x/共享名 --json

# 4. 统计一层目录大小
python scripts/minas.py du //192.168.x.x/共享名 --max-depth 1
```

Windows UNC 也可以：

```powershell
python scripts/minas.py ls \\192.168.x.x\共享名
```

---

## 5. 命令详解

### 5.1 `shares` — 列出共享

```powershell
python scripts/minas.py shares --host 192.168.x.x
python scripts/minas.py shares --host 192.168.x.x --json
```

### 5.2 `ls` — 列目录

```powershell
python scripts/minas.py ls //HOST/SHARE
python scripts/minas.py ls //HOST/SHARE/folder --json
```

### 5.3 `du` — 目录体积

```powershell
python scripts/minas.py du //HOST/SHARE --max-depth 2
```

**务必限制 `--max-depth`**，避免扫超大目录卡住。

### 5.4 `tree` — 树形结构

```powershell
python scripts/minas.py tree //HOST/SHARE --max-depth 2
```

### 5.5 `df` — 容量

```powershell
python scripts/minas.py df //HOST/SHARE
python scripts/minas.py df //HOST/SHARE --json
```

### 5.6 `get` / `put` / `cat` — 传文件

```powershell
python scripts/minas.py get //HOST/SHARE/a.txt .\a.txt
python scripts/minas.py put .\a.txt //HOST/SHARE/backup/a.txt
python scripts/minas.py cat //HOST/SHARE/notes.txt
```

### 5.7 `mkdir` / `mv` / `cp` / `rm`

```powershell
python scripts/minas.py mkdir //HOST/SHARE/work
python scripts/minas.py mv //HOST/SHARE/a.txt //HOST/SHARE/work/a.txt
python scripts/minas.py cp //HOST/SHARE/a.txt //HOST/SHARE/a.bak
python scripts/minas.py rm //HOST/SHARE/work --recursive
```

`rm --recursive` 删除目录前，请先确认用户同意。

### 5.8 `find` — 查找

```powershell
python scripts/minas.py find //HOST/SHARE --name "*.jpg" --max-depth 3 --files
python scripts/minas.py find //HOST/SHARE --name "*备份*" --json
```

---

## 6. 给 Agent 的推荐流程

```text
1. shares          → 有哪些共享
2. ls / tree       → 结构
3. du --max-depth  → 哪里占空间
4. 明确要做什么    → 需要时向用户确认
5. get 到本地工作区 → 处理 → put 回去
6. 大范围删除前再次确认
```

**退出码**

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误 / 参数问题 |
| 2 | 路径不存在 |
| 3 | 权限或网络问题 |

---

## 7. 常见问题

**Q: 看不到共享？**  
先在资源管理器地址栏输入 `\\NAS_IP\` 看能否浏览；到官方 App/客户端检查「Samba / 共享」是否开启。

**Q: 提示 1219（多重凭据）？**

```powershell
net use * /delete /y
```

然后只用一种账号重新访问。

**Q: 中文共享名/文件名乱码？**  
请使用与资源管理器中显示一致的名称；CLI 不会擅自改名。

**Q: 和 WebDAV 有什么区别？**

| | Samba（本工具） | WebDAV |
|---|---|---|
| 端口 | 445 | 通常 5000 |
| 适合 | 局域网批量文件 | 远程、部分分享 |
| 本工具 | **默认** | 非本版重点 |

**Q: 能不能挂成盘符？**  
可以自己用 `net use Z: \\NAS\share`，但本 Skill 不托管挂载，避免开机项和凭据残留。

---

## 8. 安全须知

1. 只在自有/授权设备上使用  
2. 不要把 `MINAS_PASS`、完整账号写进 Git、笔记或聊天记录  
3. 公开分享仓库前确认 `.gitignore` 已排除 `*.pem` / `.env` / 密码文件  
4. 对不可恢复的删除操作保持谨慎  

---

## 9. 目录结构

```text
minas-skill/
  SKILL.md                 # Agent 技能说明
  README.md                # 本使用文档
  scripts/minas.py         # CLI
  references/
    samba-surface.md       # 探测结论
    examples.md            # 示例
  docs/USAGE.md            # 与 README 同步的使用说明
  .gitignore
```

---

## 10. 反馈与限制

- 当前以 **Windows SMB 客户端** 为主路径  
- Linux/macOS 可改用 `smbclient` / `mount.cifs`（文档未展开）  
- 共享范围以小米智能存储里实际开启的 Samba 共享为准  

祝整理愉快。
