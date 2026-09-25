# 常见任务示例

以下 `HOST` / `SHARE` 请换成你的 NAS 地址与共享名。

## 1. 看看 NAS 上有什么

```powershell
python scripts/minas.py shares --host HOST
python scripts/minas.py ls //HOST/SHARE
python scripts/minas.py tree //HOST/SHARE --max-depth 2
```

## 2. 找出占空间的目录

```powershell
python scripts/minas.py du //HOST/SHARE --max-depth 1
python scripts/minas.py du //HOST/SHARE/photos --max-depth 2
```

## 3. 备份本机文件夹到 NAS

```powershell
python scripts/minas.py mkdir //HOST/SHARE/backup/2026-09
python scripts/minas.py put .\report.pdf //HOST/SHARE/backup/2026-09/report.pdf
```

## 4. 把 NAS 文件拉到本地处理

```powershell
python scripts/minas.py get //HOST/SHARE/raw/video.mp4 .\work\video.mp4
# ... 本地处理 ...
python scripts/minas.py put .\work\video_out.mp4 //HOST/SHARE/out/video_out.mp4
```

## 5. 按扩展名找文件

```powershell
python scripts/minas.py find //HOST/SHARE --name "*.jpg" --files --max-depth 4
python scripts/minas.py find //HOST/SHARE --name "*.zip" --json --max-depth 3
```

## 6. 建工作区并改名

```powershell
python scripts/minas.py mkdir //HOST/SHARE/work
python scripts/minas.py mv //HOST/SHARE/IMG_0001.jpg //HOST/SHARE/work/2026_trip_001.jpg
```

## 7. 清理前先确认（Agent 规范）

```text
Agent: 目录 //HOST/SHARE/old 有 12GB，确认可以删除吗？
用户: 确认删除
Agent: python scripts/minas.py rm //HOST/SHARE/old --recursive
```

## 8. 批量整理推荐流程

```text
du --max-depth 1
  → 选定目标目录
  → get 拉到本地 work/
  → 本地脚本处理
  → put / mv 回 NAS
  → ls 验证
```

## 9. JSON 供程序解析

```powershell
python scripts/minas.py ls //HOST/SHARE --json | ConvertFrom-Json
python scripts/minas.py du //HOST/SHARE --max-depth 1 --json
python scripts/minas.py find //HOST/SHARE --name "*.pdf" --json
```
