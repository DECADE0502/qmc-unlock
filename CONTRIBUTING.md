# 参与贡献

## 环境

```bash
git clone https://github.com/<you>/qmc-unlock.git
cd qmc-unlock
pip install frida tkinterdnd2          # 运行依赖
pip install pyinstaller               # 只在打包时需要
```

需要 Windows + 已安装并登录的 QQ 音乐客户端（抓 key 必需）。

## 目录约定

- `qmc_unlock.py` —— 核心引擎（结构解析 / cipher / 缓存 / frida 抓 key / CLI），保持**零外部依赖**（frida 只在抓 key 时按需 import）
- `qmc-unlock-gui.py` —— 界面层，只调用 `qmc_unlock` 暴露的接口，不重复实现算法
- `docs/` —— 原理与 FAQ；改算法请同步更新 `docs/ARCHITECTURE.md`

## 提交前自检

```bash
python qmc_unlock.py doctor
python qmc_unlock.py info   "某个包含 mflac 的目录"
python qmc_unlock.py decrypt "某个文件.mflac" -o tmp --trim
ffmpeg -v error -i tmp/xxx.flac -f null -     # 应无输出（0 error）
```

## 不要提交的东西

`.gitignore` 已覆盖，但提交前留意：

- `data/`、`*.key` —— 本机解密 key，绝对不能进仓库
- `build/ dist/ *.spec *.exe *.dll` —— 构建产物
- 任何真实用户路径、账号信息

## 新增格式支持

1. 在 `parse_file()` 增加尾部布局识别（返回 `format / audio_size / ekey`）
2. 若是新算法，实现 `decrypt(buf, offset)` 接口并在 `make_cipher()` 里分派
3. 在 `docs/ARCHITECTURE.md` 补一节结构说明
4. 附一份可复现的最小样本（能公开的分发文件或自制样本）

## 代码风格

- Python 3.8+ 语法，不引入新依赖（除非必要且能优雅降级）
- 中文注释可以，但变量/函数名用英文
- GUI 里的耗时操作必须放后台线程，通过 `Queue` 回主线程更新

## 报告问题

请附上：

- 系统版本 / Python 版本 / QQ 音乐版本
- `python qmc_unlock.py doctor` 输出
- 出错文件的 `info` 输出（**把 song_mid 打码**）
- 完整报错或日志
