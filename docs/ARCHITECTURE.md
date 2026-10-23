# 解密原理与实现细节

本文记录 qmc-unlock 的完整解密链路，以及定位关键函数的过程，方便后续适配新版本。

## 1. 文件结构（`musicex v1`）

```
┌──────────────────────────┬────────────────┬────────────┬────────────┐
│   加密音频区 audio_size    │  tail (192B)   │ tail_size  │ "musicex\0" │
└──────────────────────────┴────────────────┴────────────┴────────────┘
                                 ↑ 从文件尾 -16 处读 uint32 LE 得到 tail_size
```

解析步骤（`qmc_unlock.parse_file`）：

1. 读最后 8 字节，若等于 `b"musicex\x00"` → 判定 musicex v1
2. `seek(-16)`，读 `uint32 LE` = `tail_size`
3. `tail = read(文件大小 - 16 - tail_size, tail_size)`
   - `tail[28:88]` → UTF-16LE 去 `\0` → `song_mid`（如 `002fWpie3IjneY`）
   - `tail[88:184]` → UTF-16LE 去 `\0` → 内部文件名（如 `F0M0004Ja85V2GbwdE.mflac`）
4. `audio_size = 文件大小 - 16 - tail_size`

其它布局：

| 布局 | 判定 | key 来源 |
|---|---|---|
| `QTag` | 末 4 字节 = `QTag`，前 4 字节 = ekey 长度 | `[egkey_len][song_mid,ekey]`，自包含 |
| `STag` | 末 4 字节 = `STag` | 尾部整段是 base64 ekey，自包含 |
| `QMCv2 raw-key-tail` | 末 4 字节 = uint32 key_size 且 `< 0x300` | 尾部 key 原文 |
| `ENCV2` | 头部 `QQMusic EncV2,Key:` | 头部后跟 ekey |
| `QMCv1` | 后缀 `qmc0/qmc3/bkc*` 等 | 不需要 key（静态表） |

## 2. 取 key

`musicex v1` 文件里**只有密文**，key 不在文件内。三条来源：

### 2.1 从客户端内存抓（主路径）

QQ 音乐的 QMC 解密实现在 `CommonFunction.dll`（QQ 音乐 22.x）：

| 函数 | 作用 |
|---|---|
| `+0x9a60` | RC4 初始化：S 盒 + uint32 hash |
| `+0x9b40` | RC4 分段解密 `(buf, len, offset)` |
| `+0x98a0` | 解密调度：`if key_len > 300 → RC4，否则 Map`，两套算法都读 `this+4` 的 key |

对象布局（`this` = `ecx`）：

```
this + 0x04   -> 指向流 key 的指针（ASCII/二进制，512 字节常见）
this + 0x08   -> key 长度
this + 0x28   -> 32 位 hash
this + 0x2c   -> S 盒指针
```

所以 hook `+0x98a0` 的 `onEnter`，读 `ecx+4` / `ecx+8` 即可 dump 出 key。

版本自适应：在 `CommonFunction.dll` 里 `Memory.scanSync("2e 16 01 00")` 找 MapCipher 的
`add reg, 0x1162E`（71214），再向前回溯 `55 8B EC` 得到函数入口，作为固定偏移失效时的兜底。

### 2.2 文件内嵌

`QTag` / `STag` / `ENCV2` / `QMCv2 raw-key-tail` 自带 key，零依赖。

### 2.3 本地缓存

`data\ekeys\<song_mid>.key`（便携模式）或 `%USERPROFILE%\.qmc_unlock\ekeys\`，内容为流 key 的 hex。

**取到 key 先验证**：用它解文件前 512 字节，看是否出现 `fLaC` / `OggS` / `ID3` / AAC 帧同步，
否则判定属于别的歌并跳过（`key_fits_file`）。

## 3. ekey → 流 key（TEA 派生）

```python
raw = base64.b64decode(ekey)          # 16 ~ 上千字节

def simple_make_key(salt=106, length=8):
    return bytes(int(abs(tan(salt + i * 0.1)) * 100) & 0xFF for i in range(length))

tea_key = bytearray(16)
for i in range(8):
    tea_key[i * 2]     = simple_make_key()[i]
    tea_key[i * 2 + 1] = raw[i]

stream_key = raw[:8] + decrypt_tencent_tea(raw[8:], tea_key)
```

`decrypt_tencent_tea` 是腾讯改过的 CBC-TEA：16 轮、`delta = 0x9E3779B9`、
`PadLen(1B) + Padding(0~7B) + Salt(2B) + Body + Zero(7B)` 布局、块间用前一块密文做 CBC 异或。

带 `QQMusic EncV2,Key:` 前缀的还要先用两组固定密钥（`ENCV2_KEY1/KEY2`）做两轮同样的 TEA 解密，
再走上面的流程。

## 4. 流解密

`make_cipher(stream_key)` 按 key 长度分派：

### 4.1 MapCipher（key ≤ 300 字节）

```python
def mask(off):
    if off > 0x7FFF: off %= 0x7FFF
    idx = (off * off + 71214) % n
    return rot(key[idx], idx & 7)          # rot = ((v << s) | (v >> s)) & 0xFF, s = ((idx & 7) + 4) % 8
```

### 4.2 RC4Cipher（key > 300 字节，FLAC 常见）

```python
# 初始化：S 盒
S = list(range(n))
j = 0
for i in range(n):
    j = (j + S[i] + key[i]) % n
    S[i], S[j] = S[j], S[i]

# uint32 hash（注意溢出回绕）
h = 1
for v in key:
    if v == 0: continue
    nh = (h * v) & 0xFFFFFFFF
    if nh == 0 or nh <= h: break
    h = nh

# 分段：首段 128 字节，之后每 5120 字节一段
def seg_key(seg_id):
    seed = key[seg_id % n]
    return int(h / ((seg_id + 1) * seed) * 100) % n if seed else 0

def decrypt(buf, offset):
    # 首段
    for i in range(0, min(128 - offset, len(buf))):
        buf[i] ^= key[seg_key(offset + i)]
    # 其余段：段内先跳过 skip 步再异或
    skip = (offset % 5120) + seg_key(offset // 5120)
    # 标准 RC4 流，跳过 skip 个输出字节后开始异或
```

### 4.3 StaticCipher（QMCv1）

固定 256 字节表 `table[(off² + 27) & 0xFF]`，与文件逐字节异或。

### 4.4 C 加速

上面三种算法的 C 版本源码内嵌在 `qmc_unlock.py`（`_C_SRC`），首次运行用 gcc 编译成
`qmc2_fast.dll`；打包版直接把 dll 放程序目录。找不到 gcc 时自动回退纯 Python（慢约 40 倍）。

## 5. 输出与修尾

- 先解前 64 字节嗅探真实容器 → 决定扩展名
- 分块（100 KB）顺序解密写盘，`offset` 连续传入 cipher
- 解出的 FLAC 尾部带 QQ 音乐加密时的对齐填充（≤ 9 KB），FFmpeg 会在最后一帧报错；
  勾「修尾」时用 `ffmpeg -i in.flac -c:a flac` 无损重封装（FLAC→PCM→FLAC，音质不变），得到 0 error

## 6. 定位 `+0x98a0` 的过程（供后续适配参考）

1. frida 挂 `QQMediaPlayer.dll` 的读流函数，确认读到的仍是密文
2. 对读入缓冲区装 `MemoryAccessMonitor`，抓写入者调用栈 → 落到 `CommonFunction.dll`
3. 在该 dll 里搜 QMC 特征常量：`0x1162E`（MapCipher 的 71214）、`5120`、`float 100.0`、
   QMCv1 静态表前 8 字节
4. 交叉引用静态表 → 找到 `+0x98a0`（调度）与 `+0x9b40`（RC4），反汇编确认 `this+4/+8` 即 key
5. hook 验证：读出的 512 字节 key 能解出 `66 4C 61 43 ...`（FLAC magic）

## 7. 兼容性

| 项 | 说明 |
|---|---|
| QQ 音乐版本 | 22.28 实测（`CommonFunction.dll` 偏移如上）；其它版本靠常量回溯兜底 |
| 32/64 位 | 客户端是 32 位进程，frida 读 `ecx` 与 `esp` 参数 |
| 平台 | 抓 key 需 Windows；解密本身跨平台（只要 key 已缓存） |
| FLAC 位深 | 16/24 bit、44.1k/48k/192k 均已验证 |
