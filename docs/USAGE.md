# 使用说明

完整文档见仓库根目录 [README.md](../README.md)。

## 最短上手

1. 在官方客户端开启 Samba 共享  
2. 配置 `MINAS_HOST`（及可选 `MINAS_USER` / `MINAS_PASS`）  
3. 运行：

```powershell
python scripts/minas.py shares --host <NAS_IP>
python scripts/minas.py ls //<NAS_IP>/<共享名>
```

## Agent 必读

见 [SKILL.md](../SKILL.md) 中的「Agent 行为约束」。

## 示例

见 [references/examples.md](../references/examples.md)。
