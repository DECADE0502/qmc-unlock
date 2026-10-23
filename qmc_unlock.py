#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qmc-unlock  ——  离线 QQ 音乐加密音频解锁工具（不联网、不要 cookie、不要登录 API）

支持的格式
    .mflac .mflac0 .mgg .mgg0 .mgg1 .mggl
    .qmcflac .qmcogg .qmc0 .qmc2 .qmc3 .bkcmp3 .bkcflac .tkm
    尾部布局：musicex v1 / QTag / STag / QMCv2 raw-key-tail / QMCv1 静态表

key 来源（全部离线）
    --ekey B64            直接给 ekey（base64 串，可从别处粘贴一次）
    --ekey-dir DIR        从目录里读 <songmid>.txt / <filemid>.txt 形式的 ekey
    --from-memory         扫描正在运行的 QQMusic.exe 内存，暴力定位本文件的 key
    （QTag/STag 老文件自带 ekey，完全零依赖可解）

用法
    python qmc_unlock.py info  "D:\\Music\\VipSongsDownload"
    python qmc_unlock.py decrypt "D:\\Music\\VipSongsDownload" -o out --from-memory
    python qmc_unlock.py decrypt 某文件.mflac --ekey "AA...=="
    python qmc_unlock.py findkeys "D:\\Music\\VipSongsDownload" -o keys.txt
    python qmc_unlock.py doctor

依赖：Python 3.8+；可选 gcc（首次运行自动把 QMC2 解密编译成 C 加速 DLL，快 ~40 倍）
"""

import argparse
import base64
import ctypes
import json
import math
import os
import re
import struct
import sys
import time
from pathlib import Path

VERSION = "1.0"
IS_WINDOWS = sys.platform == "win32"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─────────────────────────── 常量 ───────────────────────────

ENCV2_PREFIX = b"QQMusic EncV2,Key:"
ENCV2_KEY1 = bytes((0x33, 0x38, 0x36, 0x5A, 0x4A, 0x59, 0x21, 0x40,
                    0x23, 0x2A, 0x24, 0x25, 0x5E, 0x26, 0x29, 0x28))
ENCV2_KEY2 = bytes((0x2A, 0x24, 0x25, 0x5E, 0x26, 0x29, 0x28, 0x23,
                    0x40, 0x21, 0x33, 0x38, 0x36, 0x5A, 0x4A, 0x59))

MUSICEX_MAGIC = b"musicex\x00"
QTAG_MAGIC = b"QTag"
STAG_MAGIC = b"STag"

SUPPORTED_EXTS = {
    ".mflac", ".mflac0", ".mgg", ".mgg0", ".mgg1", ".mggl",
    ".qmcflac", ".qmcogg", ".qmc0", ".qmc2", ".qmc3",
    ".bkcmp3", ".bkcflac", ".tkm",
}

# QMCv1 静态表
STATIC_BOX = bytes([
    0x77, 0x48, 0x32, 0x73, 0xDE, 0xF2, 0xC0, 0xC8, 0x95, 0xEC, 0x30, 0xB2, 0x51, 0xC3, 0xE1, 0xA0,
    0x9E, 0xE6, 0x9D, 0xCF, 0xFA, 0x7F, 0x14, 0xD1, 0xCE, 0xB8, 0xDC, 0xC3, 0x4A, 0x67, 0x93, 0xD6,
    0x28, 0xC2, 0x91, 0x70, 0xCA, 0x8D, 0xA2, 0xA4, 0xF0, 0x08, 0x61, 0x90, 0x7E, 0x6F, 0xA2, 0xE0,
    0xEB, 0xAE, 0x3E, 0xB6, 0x67, 0xC7, 0x92, 0xF4, 0x91, 0xB5, 0xF6, 0x6C, 0x5E, 0x84, 0x40, 0xF7,
    0xF3, 0x1B, 0x02, 0x7F, 0xD5, 0xAB, 0x41, 0x89, 0x28, 0xF4, 0x25, 0xCC, 0x52, 0x11, 0xAD, 0x43,
    0x68, 0xA6, 0x41, 0x8B, 0x84, 0xB5, 0xFF, 0x2C, 0x92, 0x4A, 0x26, 0xD8, 0x47, 0x6A, 0x7C, 0x95,
    0x61, 0xCC, 0xE6, 0xCB, 0xBB, 0x3F, 0x47, 0x58, 0x89, 0x75, 0xC3, 0x75, 0xA1, 0xD9, 0xAF, 0xCC,
    0x08, 0x73, 0x17, 0xDC, 0xAA, 0x9A, 0xA2, 0x16, 0x41, 0xD8, 0xA2, 0x06, 0xC6, 0x8B, 0xFC, 0x66,
    0x34, 0x9F, 0xCF, 0x18, 0x23, 0xA0, 0x0A, 0x74, 0xE7, 0x2B, 0x27, 0x70, 0x92, 0xE9, 0xAF, 0x37,
    0xE6, 0x8C, 0xA7, 0xBC, 0x62, 0x65, 0x9C, 0xC2, 0x08, 0xC9, 0x88, 0xB3, 0xF3, 0x43, 0xAC, 0x74,
    0x2C, 0x0F, 0xD4, 0xAF, 0xA1, 0xC3, 0x01, 0x64, 0x95, 0x4E, 0x48, 0x9F, 0xF4, 0x35, 0x78, 0x95,
    0x7A, 0x39, 0xD6, 0x6A, 0xA0, 0x6D, 0x40, 0xE8, 0x4F, 0xA8, 0xEF, 0x11, 0x1D, 0xF3, 0x1B, 0x3F,
    0x3F, 0x07, 0xDD, 0x6F, 0x5B, 0x19, 0x30, 0x19, 0xFB, 0xEF, 0x0E, 0x37, 0xF0, 0x0E, 0xCD, 0x16,
    0x49, 0xFE, 0x53, 0x47, 0x13, 0x1A, 0xBD, 0xA4, 0xF1, 0x40, 0x19, 0x60, 0x0E, 0xED, 0x68, 0x09,
    0x06, 0x5F, 0x4D, 0xCF, 0x3D, 0x1A, 0xFE, 0x20, 0x77, 0xE4, 0xD9, 0xDA, 0xF9, 0xA4, 0x2B, 0x76,
    0x1C, 0x71, 0xDB, 0x00, 0xBC, 0xFD, 0x0C, 0x6C, 0xA5, 0x47, 0xF7, 0xF6, 0x00, 0x79, 0x4A, 0x11,
])

def _portable_home():
    """
    便携模式：程序所在目录有 portable.txt 或 data 目录时，把缓存/配置都放这里，
    整个文件夹拷走即用，不写用户目录、不写注册表。
    """
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).resolve().parent)
    cands.append(Path(__file__).resolve().parent)
    for base in cands:
        try:
            if (base / "portable.txt").exists() or (base / "data").is_dir():
                d = base / "data"
                d.mkdir(parents=True, exist_ok=True)
                probe = d / ".write_test"
                probe.write_text("1", encoding="utf-8")
                probe.unlink()
                return d
        except Exception:
            continue
    return None


def _default_home():
    env = os.environ.get("QMC_UNLOCK_HOME")
    if env:
        return Path(env)
    p = _portable_home()
    if p is not None:
        return p
    return Path.home() / ".qmc_unlock"


CACHE_DIR = _default_home()
EKEY_DIR = CACHE_DIR / "ekeys"
CACCEL_DIR = CACHE_DIR / "caccel"


# ─────────────────────────── Tencent TEA / key 派生 ───────────────────────────

def simple_make_key(salt: int, length: int) -> bytes:
    buf = bytearray(length)
    for i in range(length):
        buf[i] = int(abs(math.tan(float(salt) + float(i) * 0.1)) * 100.0) & 0xFF
    return bytes(buf)


def tea_decrypt_block(block: bytes, key: bytes) -> bytes:
    v0, v1 = struct.unpack(">II", block)
    k0, k1, k2, k3 = struct.unpack(">4I", key)
    delta = 0x9E3779B9
    total = (delta * 16) & 0xFFFFFFFF
    for _ in range(16):
        v1 = (v1 - (((v0 << 4) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & 0xFFFFFFFF
        v0 = (v0 - (((v1 << 4) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & 0xFFFFFFFF
        total = (total - delta) & 0xFFFFFFFF
    return struct.pack(">II", v0, v1)


def decrypt_tencent_tea(in_buf: bytes, key: bytes):
    if len(in_buf) % 8 != 0 or len(in_buf) < 16:
        return None
    dest_buf = bytearray(tea_decrypt_block(in_buf[:8], key))
    pad_len = dest_buf[0] & 0x07
    out_len = len(in_buf) - 1 - pad_len - 2 - 7
    if out_len <= 0:
        return None
    out = bytearray(out_len)
    iv_prev, iv_cur = bytes(8), in_buf[:8]
    in_pos, dest_idx = 8, 1 + pad_len

    def crypt_block():
        nonlocal iv_prev, iv_cur, in_pos, dest_buf, dest_idx
        iv_prev = iv_cur
        iv_cur = in_buf[in_pos:in_pos + 8]
        dest_buf = bytearray(dest_buf[i] ^ in_buf[in_pos + i] for i in range(8))
        dest_buf = bytearray(tea_decrypt_block(bytes(dest_buf), key))
        in_pos += 8
        dest_idx = 0

    i = 0
    while i < 2:
        if dest_idx < 8:
            dest_idx += 1
            i += 1
        else:
            crypt_block()
    out_pos = 0
    while out_pos < out_len:
        if dest_idx < 8:
            out[out_pos] = dest_buf[dest_idx] ^ iv_prev[dest_idx]
            dest_idx += 1
            out_pos += 1
        else:
            crypt_block()
    return bytes(out)


def _decrypt_encv2(raw: bytes):
    payload = raw[len(ENCV2_PREFIX):]
    dec1 = decrypt_tencent_tea(payload, ENCV2_KEY1)
    if dec1 is None:
        return None
    dec2 = decrypt_tencent_tea(dec1, ENCV2_KEY2)
    if dec2 is None:
        return None
    try:
        return base64.b64decode(dec2)
    except Exception:
        return None


def derive_key(raw_key_dec: bytes):
    """raw(base64 解出来的 ekey) → 真正的 QMC 流 key"""
    if not raw_key_dec or len(raw_key_dec) < 16:
        return None
    if raw_key_dec[:len(ENCV2_PREFIX)] == ENCV2_PREFIX:
        raw_key_dec = _decrypt_encv2(raw_key_dec)
        if raw_key_dec is None or len(raw_key_dec) < 16:
            return None
    simple = simple_make_key(106, 8)
    tea_key = bytearray(16)
    for i in range(8):
        tea_key[i * 2] = simple[i]
        tea_key[i * 2 + 1] = raw_key_dec[i]
    rs = decrypt_tencent_tea(raw_key_dec[8:], bytes(tea_key))
    if rs is None:
        return None
    return raw_key_dec[:8] + rs


def ekey_to_key(ekey_b64: str):
    """ekey(base64 文本) → 流 key"""
    ekey_b64 = (ekey_b64 or "").strip()
    if not ekey_b64:
        return None
    try:
        raw = base64.b64decode(ekey_b64)
    except Exception:
        try:
            raw = base64.b64decode(ekey_b64 + "=" * (-len(ekey_b64) % 4))
        except Exception:
            return None
    return derive_key(raw)


# ─────────────────────────── Cipher ───────────────────────────

def _map_mask(key: bytes, n: int, offset: int) -> int:
    if n == 0:
        return 0
    if offset > 0x7FFF:
        offset %= 0x7FFF
    idx = (offset * offset + 71214) % n
    shift = (idx & 0x07) + 4
    shift %= 8
    v = key[idx]
    return ((v << shift) | (v >> shift)) & 0xFF


class MapCipher:
    """key <= 300 字节"""

    def __init__(self, key: bytes):
        self.key = key
        self.n = len(key)

    def decrypt(self, buf: bytearray, offset: int = 0) -> None:
        key, n = self.key, self.n
        for i in range(len(buf)):
            buf[i] ^= _map_mask(key, n, offset + i)


class RC4Cipher:
    """key > 300 字节"""

    SEGMENT_SIZE = 5120
    FIRST_SEGMENT_SIZE = 128

    def __init__(self, key: bytes):
        self.key = key
        self.n = len(key)
        self.box = [i & 0xFF for i in range(self.n)]
        j = 0
        for i in range(self.n):
            j = (j + self.box[i] + key[i]) % self.n
            self.box[i], self.box[j] = self.box[j], self.box[i]
        self.hash = self._compute_hash()

    def _compute_hash(self) -> int:
        h = 1
        for v in self.key:
            if v == 0:
                continue
            nh = (h * v) & 0xFFFFFFFF
            if nh == 0 or nh <= h:
                break
            h = nh
        return h

    def _skip(self, id_val: int) -> int:
        seed = int(self.key[id_val % self.n])
        if seed == 0:
            return 0
        idx = int(float(self.hash) / float((id_val + 1) * seed) * 100.0)
        return idx % self.n

    def _first_segment(self, buf: bytearray, buf_off: int, length: int, stream_off: int) -> None:
        for i in range(length):
            buf[buf_off + i] ^= self.key[self._skip(stream_off + i)]

    def _a_segment(self, buf: bytearray, buf_off: int, length: int, stream_off: int) -> None:
        box = self.box.copy()
        j = k = 0
        skip_len = (stream_off % self.SEGMENT_SIZE) + self._skip(stream_off // self.SEGMENT_SIZE)
        for i in range(-skip_len, length):
            j = (j + 1) % self.n
            k = (box[j] + k) % self.n
            box[j], box[k] = box[k], box[j]
            if i >= 0:
                buf[buf_off + i] ^= box[(box[j] + box[k]) % self.n]

    def decrypt(self, buf: bytearray, offset: int = 0) -> None:
        to_process = len(buf)
        processed = 0
        if offset < self.FIRST_SEGMENT_SIZE:
            block = min(to_process, self.FIRST_SEGMENT_SIZE - offset)
            self._first_segment(buf, 0, block, offset)
            processed += block
            offset += block
            to_process -= block
            if to_process == 0:
                return
        if offset % self.SEGMENT_SIZE != 0:
            block = min(to_process, self.SEGMENT_SIZE - offset % self.SEGMENT_SIZE)
            self._a_segment(buf, processed, block, offset)
            processed += block
            offset += block
            to_process -= block
            if to_process == 0:
                return
        while to_process > self.SEGMENT_SIZE:
            self._a_segment(buf, processed, self.SEGMENT_SIZE, offset)
            processed += self.SEGMENT_SIZE
            offset += self.SEGMENT_SIZE
            to_process -= self.SEGMENT_SIZE
        if to_process > 0:
            self._a_segment(buf, processed, to_process, offset)


class StaticCipher:
    """QMCv1"""

    def decrypt(self, buf: bytearray, offset: int = 0) -> None:
        for i in range(len(buf)):
            off = offset + i
            if off > 0x7FFF:
                off %= 0x7FFF
            buf[i] ^= STATIC_BOX[(off * off + 27) & 0xFF]


def make_cipher(key: bytes):
    return RC4Cipher(key) if len(key) > 300 else MapCipher(key)


# ─────────────────────────── C 加速（可选） ───────────────────────────

_C_SRC = r"""
#include <stdlib.h>
#include <string.h>
static unsigned char map_rotate(unsigned char v, int bits){int s=((bits&7)+4)%8;return (unsigned char)(((v<<s)|(v>>s))&0xFF);}
static unsigned char map_mask(const unsigned char*k,int n,int off){if(n==0)return 0;if(off>0x7FFF)off%=0x7FFF;int idx=(off*off+71214)%n;return map_rotate(k[idx],idx&7);}
static void map_decrypt(const unsigned char*k,int n,unsigned char*b,int len,int off){for(int i=0;i<len;i++)b[i]^=map_mask(k,n,off+i);}
static unsigned int rc4_hash(const unsigned char*k,int n){unsigned int h=1;for(int i=0;i<n;i++){if(!k[i])continue;unsigned int nh=h*(unsigned int)k[i];if(nh==0||nh<=h)break;h=nh;}return h;}
static int rc4_skip(const unsigned char*k,int n,unsigned int h,int id){long long seed=(long long)k[id%n];if(!seed)return 0;long long idx=(long long)((double)h/(double)((id+1)*seed)*100.0);return (int)(idx%n);}
static void rc4_decrypt(const unsigned char*k,int n,unsigned char*b,int len,int off){
  int *box=(int*)malloc(n*sizeof(int));for(int i=0;i<n;i++)box[i]=i&0xFF;
  int j=0;for(int i=0;i<n;i++){j=(j+box[i]+k[i])%n;int t=box[i];box[i]=box[j];box[j]=t;}
  unsigned int h=rc4_hash(k,n);int FIRST=128,SEG=5120,processed=0,pos=off;
  if(pos<FIRST){int blk=(len<(FIRST-pos))?len:(FIRST-pos);for(int i=0;i<blk;i++)b[processed+i]^=k[rc4_skip(k,n,h,pos+i)];processed+=blk;pos+=blk;}
  while(processed<len){int so=pos%SEG;int blk=SEG-so;if(blk>len-processed)blk=len-processed;
    int *bc=(int*)malloc(n*sizeof(int));memcpy(bc,box,n*sizeof(int));
    int jj=0,kk=0;int skip=so+rc4_skip(k,n,h,pos/SEG);
    for(int i=-skip;i<blk;i++){jj=(jj+1)%n;kk=(bc[jj]+kk)%n;int t=bc[jj];bc[jj]=bc[kk];bc[kk]=t;if(i>=0)b[processed+i]^=bc[(bc[jj]+bc[kk])%n];}
    free(bc);processed+=blk;pos+=blk;}
  free(box);
}
void qmc2_decrypt(const unsigned char*k,int n,unsigned char*b,int len,int off){if(n>300)rc4_decrypt(k,n,b,len,off);else map_decrypt(k,n,b,len,off);}
"""

_lib = None
_lib_tried = False


def _bundled_lib():
    """打包(exe)或同目录下自带的 C 加速库"""
    names = ("qmc2_fast.dll", "qmc2_fast.so")
    roots = [Path(__file__).resolve().parent]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(getattr(sys, "_MEIPASS", ".")))
        roots.insert(1, Path(sys.executable).resolve().parent)
    for r in roots:
        for n in names:
            p = Path(r) / n
            if p.exists():
                return p
    return None


def load_caccel():
    """编译并加载 C 加速库；不可用返回 None"""
    global _lib, _lib_tried
    if _lib is not None:
        return _lib
    if _lib_tried:
        return None
    _lib_tried = True

    # 1) 先用随程序分发的库
    bundled = _bundled_lib()
    if bundled is not None:
        try:
            lib = ctypes.CDLL(str(bundled))
            lib.qmc2_decrypt.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                         ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            lib.qmc2_decrypt.restype = None
            _lib = lib
            return _lib
        except Exception:
            pass

    # 2) 再尝试本地编译
    try:
        CACCEL_DIR.mkdir(parents=True, exist_ok=True)
        src = CACCEL_DIR / "qmc2_fast.c"
        if not src.exists():
            src.write_text(_C_SRC, encoding="utf-8")
        libname = "qmc2_fast.dll" if IS_WINDOWS else "qmc2_fast.so"
        libpath = CACCEL_DIR / libname
        if not libpath.exists():
            import subprocess
            cmd = ["gcc", "-O3", "-shared", "-o", str(libpath), str(src)]
            if not IS_WINDOWS:
                cmd.insert(3, "-fPIC")
                cmd.append("-lm")
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        lib = ctypes.CDLL(str(libpath))
        lib.qmc2_decrypt.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                     ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.qmc2_decrypt.restype = None
        _lib = lib
        return _lib
    except Exception:
        return None


def c_decrypt(key: bytes, data: bytearray, offset: int = 0) -> bool:
    lib = load_caccel()
    if lib is None:
        return False
    buf = (ctypes.c_char * len(data)).from_buffer(data)
    lib.qmc2_decrypt(key, len(key), buf, len(data), offset)
    return True


# ─────────────────────────── 文件格式解析 ───────────────────────────

def sniff_ext(data: bytes):
    if data[:4] == b"fLaC":
        return ".flac"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:3] == b"ID3":
        return ".mp3"
    if len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return ".mp3"
    if len(data) > 11 and data[4:8] == b"ftyp":
        return ".m4a"
    if data[:4] == b"RIFF":
        return ".wav"
    return None


def parse_file(path: Path) -> dict:
    """
    返回 {ok, format, song_mid, file_mid, filename, ext_hint, audio_size, ekey, error}
    """
    p = Path(path)
    size = p.stat().st_size
    ext = p.suffix.lower()
    out = {"path": str(p), "size": size, "ok": False, "format": "unknown",
           "song_mid": "", "file_mid": "", "filename": "", "ext_hint": "",
           "audio_size": size, "ekey": None}

    with open(p, "rb") as f:
        # 1) ENCV2 前缀（老 eapi 单文件）
        head = f.read(len(ENCV2_PREFIX))
        if head == ENCV2_PREFIX:
            f.seek(0)
            blob = f.read(min(size, 4096))
            nl = blob.find(b"\x00")
            if nl > 0:
                ekey = blob[len(ENCV2_PREFIX):nl].decode("ascii", "ignore")
                out.update(format="encv2", ekey=ekey, audio_size=size, ok=True)
                return out

        # 2) musicex v1 尾部
        if size >= 16:
            f.seek(-8, 2)
            if f.read(8) == MUSICEX_MAGIC:
                f.seek(-16, 2)
                tail_size = struct.unpack("<I", f.read(4))[0]
                tail_start = size - 16 - tail_size
                if 0 < tail_size <= 0x10000 and tail_start > 0:
                    f.seek(tail_start)
                    tail = f.read(tail_size)
                    song_mid = tail[28:88].decode("utf-16-le", "ignore").rstrip("\x00")
                    filename = tail[88:184].decode("utf-16-le", "ignore").rstrip("\x00")
                    file_mid = re.sub(r"\.(mflac0?|mgg\d?l?|qmc\w*)", "", filename)
                    out.update(format="musicex", song_mid=song_mid, filename=filename,
                               file_mid=file_mid, audio_size=tail_start, ok=True)
                    return out

            # 3) QTag / STag 尾部
            f.seek(-4, 2)
            tag = f.read(4)
            if tag in (QTAG_MAGIC, STAG_MAGIC):
                f.seek(-8, 2)
                ekey_len = struct.unpack("<I", f.read(4))[0]
                if 0 < ekey_len <= 8192:
                    audio_size = size - 8 - ekey_len
                    f.seek(audio_size)
                    raw = f.read(ekey_len)
                    if tag == QTAG_MAGIC:
                        parts = raw.split(b",")
                        song_mid = parts[0].decode("utf-8", "ignore") if parts else ""
                        ekey = parts[1].decode("utf-8", "ignore") if len(parts) > 1 else ""
                    else:
                        song_mid, ekey = "", raw.decode("utf-8", "ignore")
                    out.update(format="qtag" if tag == QTAG_MAGIC else "stag",
                               song_mid=song_mid, ekey=ekey, audio_size=audio_size, ok=True)
                    return out

            # 4) QMCv2 raw key tail（尾部 4 字节 = key 长度）
            f.seek(-4, 2)
            key_size = struct.unpack("<I", f.read(4))[0]
            if 0 < key_size < 0x300 and size > key_size + 8:
                audio_size = size - key_size - 4
                f.seek(audio_size)
                raw_key = f.read(key_size)
                out.update(format="qmc2-tail", ekey=raw_key.decode("ascii", "ignore"),
                           audio_size=audio_size, ok=True)
                return out

    # 5) QMCv1（qmc0/qmc3/bkcmp3...）→ 静态表
    if ext in {".qmc0", ".qmc2", ".qmc3", ".bkcmp3", ".bkcflac", ".tkm"}:
        out.update(format="qmc1", audio_size=size, ok=True)
        return out

    # 6) 尾部分析失败时的兜底：按扩展名猜 v2，用内存/缓存 key
    if ext in SUPPORTED_EXTS:
        out.update(format="qmc2-unknown", audio_size=size, ok=True)
        return out

    out["error"] = f"不支持的扩展名: {ext}"
    return out


# ─────────────────────────── ekey 缓存 ───────────────────────────

def _cache_keys(m: dict):
    keys = []
    if m.get("song_mid"):
        keys.append(m["song_mid"])
    if m.get("file_mid"):
        keys.append(m["file_mid"])
    if m.get("filename"):
        keys.append(Path(m["filename"]).stem)
    return [k for k in keys if k]


def load_cached_ekey(m: dict, extra_dirs=()):
    dirs = [EKEY_DIR] + [Path(d) for d in extra_dirs if d]
    for k in _cache_keys(m):
        for d in dirs:
            p = d / f"{k}.txt"
            if p.exists():
                txt = p.read_text(encoding="utf-8", errors="ignore").strip()
                if txt:
                    return txt
    return None


def save_cached_ekey(m: dict, ekey: str):
    try:
        EKEY_DIR.mkdir(parents=True, exist_ok=True)
        for k in _cache_keys(m):
            (EKEY_DIR / f"{k}.txt").write_text(ekey, encoding="utf-8")
    except Exception:
        pass


def load_cached_rawkey(m: dict, extra_dirs=()):
    """读取已派生好的 QMC 流 key（.key 文件，内容为 hex）"""
    dirs = [EKEY_DIR] + [Path(d) for d in extra_dirs if d]
    for k in _cache_keys(m):
        for d in dirs:
            for name in (f"{k}.key", f"{k}.rawkey"):
                p = d / name
                if p.exists():
                    raw = rawkey_from_text(p.read_text(encoding="utf-8", errors="ignore"))
                    if raw:
                        return raw
    return None


def save_cached_rawkey(m: dict, key: bytes):
    try:
        EKEY_DIR.mkdir(parents=True, exist_ok=True)
        for k in _cache_keys(m):
            (EKEY_DIR / f"{k}.key").write_text(key.hex(), encoding="utf-8")
    except Exception:
        pass


def rawkey_from_text(text: str):
    """把 hex / base64 文本还原成 QMC 流 key"""
    t = (text or "").strip()
    if not t:
        return None
    compact = "".join(t.split())
    if re.fullmatch(r"[0-9a-fA-F]+", compact) and len(compact) % 2 == 0:
        try:
            raw = bytes.fromhex(compact)
            if len(raw) >= 16:
                return raw
        except Exception:
            pass
    try:
        raw = base64.b64decode(compact + "=" * (-len(compact) % 4))
        if len(raw) >= 16:
            return raw
    except Exception:
        pass
    return None


# ─────────────────────────── Windows 进程内存 ───────────────────────────

class ProcessMemory:
    def __init__(self, pid: int):
        if not IS_WINDOWS:
            raise RuntimeError("内存扫描仅支持 Windows")
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_VM_READ = 0x0010
        PROCESS_QUERY_INFORMATION = 0x0400
        self.handle = self.k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.handle:
            raise RuntimeError(f"无法打开进程 {pid}（需要管理员权限）:{ctypes.get_last_error()}")

    class MBI(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", ctypes.c_ulong), ("RegionSize", ctypes.c_size_t),
                    ("State", ctypes.c_ulong), ("Protect", ctypes.c_ulong),
                    ("Type", ctypes.c_ulong)]

    def regions(self):
        MEM_COMMIT = 0x1000
        READABLE = {0x02, 0x04, 0x06, 0x20, 0x40, 0x60, 0x80}
        mbi = self.MBI()
        addr = 0
        while addr < 0x7FFFFFFFFFFF:
            if self.k32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr),
                                       ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize or 0
            if size == 0:
                break
            if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE and size <= 64 * 1024 * 1024:
                yield base, size
            nxt = base + size
            if nxt <= addr:
                break
            addr = nxt

    def read(self, base: int, size: int):
        buf = (ctypes.c_char * size)()
        got = ctypes.c_size_t(0)
        if self.k32.ReadProcessMemory(self.handle, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
            return bytes(buf[:got.value])
        return None

    def iter_blocks(self, max_block=8 * 1024 * 1024):
        for base, size in self.regions():
            off = 0
            while off < size:
                chunk = min(max_block, size - off)
                data = self.read(base + off, chunk)
                if data:
                    yield base + off, data
                off += chunk

    def close(self):
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


def find_qqmusic_pids():
    if not IS_WINDOWS:
        return []
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq QQMusic.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "qqmusic.exe":
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


B64_RE = re.compile(rb"[A-Za-z0-9+/]{16,2048}={0,2}")


def key_probe_ok(key: bytes, probe: bytes, audio_size: int) -> bool:
    """拿 key 试解 probe(文件开头)，看像不像真音频"""
    if not key or len(key) < 16:
        return False
    buf = bytearray(probe)
    try:
        if not c_decrypt(key, buf, 0):
            make_cipher(key).decrypt(buf, 0)
    except Exception:
        return False
    if sniff_ext(bytes(buf[:16])):
        return True
    # 弱判定：FLAC 帧同步 / Ogg 页
    return buf[:4] in (b"fLaC", b"OggS") or (buf[0] == 0xFF and (buf[1] & 0xE0) == 0xE0)


def scan_memory_for_keys(probes: dict, pids=None, verbose=True):
    """
    probes: {"label": (probe_bytes, audio_size)}
    返回 {label: ekey_b64}
    """
    if pids is None:
        pids = find_qqmusic_pids()
    if not pids:
        if verbose:
            print("[!] 没发现 QQMusic.exe 进程。请先启动 QQ 音乐（不需要登录操作，客户端会自己保持登录态）", file=sys.stderr)
        return {}
    found = {}
    tried = 0
    seen = set()
    t0 = time.time()
    for pid in pids:
        if verbose:
            print(f"[*] 扫描 QQMusic.exe (PID {pid}) 内存 …", file=sys.stderr)
        try:
            pm = ProcessMemory(pid)
        except Exception as e:
            if verbose:
                print(f"[!] {e}", file=sys.stderr)
            continue
        try:
            for base, data in pm.iter_blocks():
                if all(k in found for k in probes):
                    break
                for mobj in B64_RE.finditer(data):
                    cand = mobj.group()
                    if cand in seen:
                        continue
                    seen.add(cand)
                    tried += 1
                    raw = None
                    try:
                        raw = base64.b64decode(cand + b"=" * (-len(cand) % 4))
                    except Exception:
                        continue
                    if len(raw) < 16 or len(raw) > 4096:
                        continue
                    key = derive_key(raw)
                    if not key:
                        continue
                    for label, (probe, asize) in probes.items():
                        if label in found:
                            continue
                        if key_probe_ok(key, probe, asize):
                            ekey = cand.decode("ascii")
                            found[label] = ekey
                            if verbose:
                                print(f"[+] 命中 {label}  ←  ekey {len(ekey)} 字符 "
                                      f"(key {len(key)}B)", file=sys.stderr)
                if all(k in found for k in probes):
                    break
        finally:
            pm.close()
    if verbose:
        print(f"[*] 扫描完成：候选 {tried} 个，命中 {len(found)}/{len(probes)}，"
              f"耗时 {time.time()-t0:.1f}s", file=sys.stderr)
    return found


# ─────────────────────────── 从客户端抓 key（frida） ───────────────────────────

CLIENT_HOOK_JS = r"""
var targets = [];
var cf = null;
try { cf = Process.getModuleByName("CommonFunction.dll"); } catch (e) {}
if (cf) {
  // 已知偏移（QQ 音乐 22.x / CommonFunction.dll 0x98a0 = QMC 解密调度）
  targets.push({name: "dispatch", addr: cf.base.add(0x98a0)});
  // 自适应：找 map 常量 0x1162E（add reg, 2e 16 01 00）向前回溯函数入口
  try {
    Memory.scanSync(cf.base, cf.size, "2e 16 01 00").forEach(function (hit) {
      var lo = hit.address.sub(0x800);
      try {
        var buf = new Uint8Array(lo.readByteArray(0x800));
        var best = null;
        for (var i = 0; i + 3 <= buf.length; i++) {
          if (buf[i] === 0x55 && buf[i + 1] === 0x8b && buf[i + 2] === 0xec) best = lo.add(i);
        }
        if (best) targets.push({name: "auto", addr: best});
      } catch (e) {}
    });
  } catch (e) {}
}

var cur = "";
function stampFile(w) {
  if (w && /\.(mflac0?|mgg\d?l?|qmcflac|qmcogg|qmc0|qmc2|qmc3)\s*$/i.test(w)) { cur = w; send({opened: w}); }
}
try {
  var cfh = Process.getModuleByName("kernel32.dll").getExportByName("CreateFileW");
  Interceptor.attach(cfh, {
    onEnter: function (a) { try { stampFile(a[0].readUtf16String()); } catch (e) {} }
  });
} catch (e) {}

var sent = {};
function emitKey(hex, len, tag) {
  var k = hex.substring(0, 96);
  if (sent[k]) return;
  sent[k] = true;
  send({key: hex, len: len, file: cur, from: tag});
}

var hooked = 0;
targets.forEach(function (t) {
  try {
    Interceptor.attach(t.addr, {
      onEnter: function () {
        var ecx = this.context.ecx;
        try {
          var kp = ecx.add(4).readPointer();
          var kl = ecx.add(8).readU32();
          if (kl > 8 && kl < 8192) {
            var b = new Uint8Array(kp.readByteArray(kl));
            var hex = "";
            for (var i = 0; i < b.length; i++) hex += ("0" + b[i].toString(16)).slice(-2);
            emitKey(hex, kl, t.name);
          }
        } catch (e) {}
      }
    });
    hooked++;
  } catch (e) {}
});
send({ready: true, modules: !!cf, hooked: hooked});
"""


def find_qqmusic_exe():
    for p in (r"C:\Program Files (x86)\Tencent\QQMusic\QQMusic.exe",
              r"C:\Program Files\Tencent\QQMusic\QQMusic.exe",
              r"D:\Program Files\Tencent\QQMusic\QQMusic.exe"):
        if os.path.exists(p):
            return p
    return None


def grab_keys_from_client(files, metas, timeout=None, verbose=True):
    """
    让 QQ 音乐客户端依次打开这些文件，hook 其 QMC 解密函数抓流 key。
    返回 {file_path: key_bytes}
    """
    try:
        import frida, subprocess
    except ImportError:
        if verbose:
            print("[!] 未安装 frida：pip install frida  （抓 key 需要它）", file=sys.stderr)
        return {}

    exe = find_qqmusic_exe()
    if not exe:
        if verbose:
            print("[!] 找不到 QQMusic.exe", file=sys.stderr)
        return {}

    if not find_qqmusic_pids():
        if verbose:
            print("[*] QQ 音乐未运行，正在启动 …", file=sys.stderr)
        subprocess.Popen([exe])
        for _ in range(40):
            time.sleep(1)
            if find_qqmusic_pids():
                break
    if not find_qqmusic_pids():
        if verbose:
            print("[!] QQ 音乐启动失败", file=sys.stderr)
        return {}

    dev = frida.get_local_device()
    pid = find_qqmusic_pids()[0]
    session = dev.attach(pid)
    script = session.create_script(CLIENT_HOOK_JS)
    found = {}
    opened = {"path": ""}

    def on_message(msg, data):
        if msg.get("type") != "send":
            return
        p = msg.get("payload") or {}
        if "opened" in p:
            opened["path"] = p["opened"]
        if "key" in p:
            path = p.get("file") or opened["path"]
            try:
                key = bytes.fromhex(p["key"])
            except Exception:
                return
            if len(key) < 16:
                return
            name = os.path.basename(str(path).lstrip("\\?\\"))
            found.setdefault(name.lower(), key)
            if verbose:
                print(f"[+] 抓到 key {len(key)}B ← {name or '(未关联文件)'}", file=sys.stderr)

    script.on("message", on_message)
    script.load()
    time.sleep(1.5)

    try:
        for f in files:
            if verbose:
                print(f"[*] 让客户端打开并解密：{f.name} …", file=sys.stderr)
            subprocess.Popen([exe, str(f)])
            t0 = time.time()
            wait = timeout or 18
            while time.time() - t0 < wait:
                time.sleep(1)
                if f.name.lower() in found:
                    break
    finally:
        try:
            session.detach()
        except Exception:
            pass

    # 文件没关联上时，按顺序兜底
    if len(found) == 1 and len(files) > 1:
        only = list(found.values())[0]
        if verbose:
            print("[i] 只抓到一个 key，无法确定归属，不自动分配", file=sys.stderr)
        return {}
    return found


# ─────────────────────────── 解密 ───────────────────────────

DEC_CHUNK = 5120 * 20


def decrypt_file(path: Path, meta: dict, key: bytes, out_dir: Path,
                 overwrite=False, keep_stem=True, tag=None) -> dict:
    p = Path(path)
    audio_size = meta["audio_size"]
    # 嗅探输出格式：先解前 64 字节
    with open(p, "rb") as f:
        probe = bytearray(f.read(min(64, audio_size)))
    try:
        if not c_decrypt(key, probe, 0):
            make_cipher(key).decrypt(probe, 0)
    except Exception as e:
        return {"ok": False, "file": str(p), "error": f"解密失败: {e}"}
    ext = sniff_ext(bytes(probe[:16]))
    if ext is None:
        return {"ok": False, "file": str(p),
                "error": "key 不匹配（解出来的不是音频头）"}

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = p.stem
    if p.suffix.lower() in {e for e in SUPPORTED_EXTS}:
        stem = p.name
        for e in sorted(SUPPORTED_EXTS, key=len, reverse=True):
            if stem.lower().endswith(e):
                stem = stem[: -len(e)]
                break
    out_path = out_dir / f"{stem}{ext}"
    if out_path.exists() and not overwrite:
        base, n = out_path, 1
        while out_path.exists():
            out_path = base.with_name(f"{base.stem} ({n}){base.suffix}")
            n += 1

    cipher = None if load_caccel() else make_cipher(key)
    with open(p, "rb") as fin, open(out_path, "wb") as fout:
        offset = 0
        while offset < audio_size:
            n = min(DEC_CHUNK, audio_size - offset)
            buf = bytearray(fin.read(n))
            if len(buf) != n:
                break
            if cipher is None:
                c_decrypt(key, buf, offset)
            else:
                cipher.decrypt(buf, offset)
            fout.write(buf)
            offset += n
    return {"ok": True, "file": str(p), "output": str(out_path), "ext": ext,
            "bytes": audio_size, "size": out_path.stat().st_size}


# ─────────────────────────── 收集文件 ───────────────────────────

def collect_files(targets, recursive=True):
    files = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                    files.append(f)
        elif p.is_file():
            files.append(p)
        else:
            print(f"[!] 不存在: {p}", file=sys.stderr)
    return files


def prepare_probe(path: Path, meta: dict):
    with open(path, "rb") as f:
        return f.read(min(512, meta["audio_size"]))


def key_fits_file(path: Path, meta: dict, key: bytes) -> bool:
    """用 key 试解文件头，判断是不是这个文件的 key"""
    probe = bytearray(prepare_probe(path, meta))
    try:
        if not c_decrypt(key, probe, 0):
            make_cipher(key).decrypt(probe, 0)
    except Exception:
        return False
    return sniff_ext(bytes(probe[:16])) is not None


# ─────────────────────────── 命令 ───────────────────────────

def cmd_info(args):
    files = collect_files(args.targets)
    if not files:
        print("没找到可处理的加密文件", file=sys.stderr)
        return 1
    rows = []
    for f in files:
        m = parse_file(f)
        row = {"file": str(f), "size": m["size"], "format": m["format"],
               "audio_size": m["audio_size"], "song_mid": m["song_mid"],
               "file_mid": m["file_mid"], "embedded_ekey": bool(m.get("ekey")),
               "cached_key": bool(load_cached_ekey(m, args.ekey_dir)
                                  or load_cached_rawkey(m, args.ekey_dir))}
        if args.json:
            rows.append(row)
        else:
            print(f"{f.name}")
            print(f"    格式       : {m['format']}")
            print(f"    文件大小   : {m['size']:,} B   音频区: {m['audio_size']:,} B")
            print(f"    song_mid   : {m['song_mid'] or '-'}")
            print(f"    file_mid   : {m['file_mid'] or '-'}   ({m['filename'] or '-'})")
            print(f"    内嵌 ekey  : {'有' if m.get('ekey') else '无（musicex 格式需要外部 key）'}")
            print(f"    已缓存 key: {'有（可离线解密）' if row['cached_key'] else '无'}")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_decrypt(args):
    files = collect_files(args.targets)
    if not files:
        print("没找到可处理的加密文件", file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else (files[0].parent if len(files) == 1 else Path.cwd())

    metas = {f: parse_file(f) for f in files}
    keys = {}          # file -> 派生后的 QMC 流 key（bytes）
    key_src = {}

    def key_fits(f, key):
        return key_fits_file(f, metas[f], key)

    # 0) 命令行直接给流 key（hex / base64）
    raw_cli = None
    if getattr(args, "key_hex", None):
        raw_cli = rawkey_from_text(args.key_hex)
    if raw_cli is None and getattr(args, "key_file", None):
        try:
            raw_cli = rawkey_from_text(Path(args.key_file).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            raw_cli = None
    if raw_cli is not None:
        for f in files:
            if key_fits(f, raw_cli):
                keys[f] = raw_cli
                key_src[f] = "--key"
                save_cached_rawkey(metas[f], raw_cli)
        if not keys:
            print("[!] 给的流 key 解不开这些文件（不匹配）", file=sys.stderr)

    # 1) 命令行 ekey
    if args.ekey:
        k = ekey_to_key(args.ekey)
        if not k:
            print("[!] --ekey 解析失败（不是合法 base64 ekey）", file=sys.stderr)
        else:
            for f in files:
                keys[f] = k
                key_src[f] = "--ekey"

    # 2) 内嵌 ekey（QTag/STag/ENCV2/qmc2-tail）
    for f, m in metas.items():
        if f in keys:
            continue
        if m.get("ekey"):
            k = ekey_to_key(m["ekey"])
            if k:
                keys[f] = k
                key_src[f] = "内嵌"
                save_cached_ekey(m, m["ekey"])

    # 3) 本地缓存：ekey 缓存（.txt）与流 key 缓存（.key）
    for f, m in metas.items():
        if f in keys:
            continue
        ek = load_cached_ekey(m, args.ekey_dir)
        if ek:
            k = ekey_to_key(ek)
            if k:
                keys[f] = k
                key_src[f] = "缓存(ekey)"
                continue
        rk = load_cached_rawkey(m, args.ekey_dir)
        if rk:
            keys[f] = rk
            key_src[f] = "缓存(key)"

    # 4) 内存扫描（针对还缺 key 的文件）
    missing = [f for f in files if f not in keys]
    if missing and (args.from_memory or args.auto_memory):
        probes = {}
        for f in missing:
            probes[str(f)] = (prepare_probe(f, metas[f]), metas[f]["audio_size"])
        print(f"[*] {len(missing)} 个文件缺 key，开始在 QQMusic.exe 内存里找 …", file=sys.stderr)
        hits = scan_memory_for_keys(probes)
        for f in missing:
            ek = hits.get(str(f))
            if ek:
                k = ekey_to_key(ek)
                if k:
                    keys[f] = k
                    key_src[f] = "内存"
                    save_cached_ekey(metas[f], ek)

    # 4b) 从 QQ 音乐客户端抓流 key（frida hook 解密函数）
    missing = [f for f in files if f not in keys]
    if missing and (args.from_client or args.auto_client):
        grabbed = grab_keys_from_client(missing, metas)
        for f in missing:
            k = grabbed.get(f.name.lower())
            if k and key_fits(f, k):
                keys[f] = k
                key_src[f] = "客户端"
                save_cached_rawkey(metas[f], k)
            elif k:
                print(f"[!] {f.name}: 抓到的 key 解不开该文件（可能是别的歌）", file=sys.stderr)

    # 5) v1 静态表兜底
    for f, m in metas.items():
        if f in keys:
            continue
        if m["format"] in ("qmc1",):
            keys[f] = None
            key_src[f] = "QMCv1静态表"

    results = []
    okc = 0
    for f in files:
        m = metas[f]
        if f not in keys:
            msg = "缺 key：无内嵌 ekey、无缓存、内存也没扫到；可用 --ekey 指定"
            print(f"[x] {f.name} → {msg}", file=sys.stderr)
            results.append({"ok": False, "file": str(f), "error": msg})
            continue
        key = keys[f]
        if key is None:  # QMCv1
            with open(f, "rb") as fh:
                probe = bytearray(fh.read(min(64, m["audio_size"])))
            StaticCipher().decrypt(probe, 0)
            ext = sniff_ext(bytes(probe[:16])) or ".mp3"
            out_path = out_dir / f"{_stem(f)}{ext}"
            if out_path.exists() and not args.overwrite:
                base, n = out_path, 1
                while out_path.exists():
                    out_path = base.with_name(f"{base.stem} ({n}){base.suffix}")
                    n += 1
            out_dir.mkdir(parents=True, exist_ok=True)
            sc = StaticCipher()
            with open(f, "rb") as fin, open(out_path, "wb") as fout:
                off = 0
                while off < m["audio_size"]:
                    n = min(DEC_CHUNK, m["audio_size"] - off)
                    buf = bytearray(fin.read(n))
                    if len(buf) != n:
                        break
                    sc.decrypt(buf, off)
                    fout.write(buf)
                    off += n
            r = {"ok": True, "file": str(f), "output": str(out_path), "ext": ext}
        else:
            r = decrypt_file(f, m, key, out_dir, overwrite=args.overwrite)
        r["key_source"] = key_src.get(f)
        if r.get("ok") and getattr(args, "trim", False) and r.get("ext") == ".flac":
            if trim_with_ffmpeg(Path(r["output"])):
                r["trimmed"] = True
        results.append(r)
        if r.get("ok"):
            okc += 1
            print(f"[✓] {f.name} → {Path(r['output']).name}  ({r.get('ext')}, key:{r['key_source']})")
        else:
            print(f"[x] {f.name} → {r.get('error')}", file=sys.stderr)

    print(f"\n完成：{okc}/{len(files)} 成功，输出目录 {out_dir}")
    if args.json:
        print(json.dumps({"success": okc, "total": len(files), "results": results},
                         ensure_ascii=False, indent=2))
    return 0 if okc == len(files) else 2


def _stem(p: Path) -> str:
    name = p.name
    for e in sorted(SUPPORTED_EXTS, key=len, reverse=True):
        if name.lower().endswith(e):
            return name[: -len(e)]
    return p.stem


def trim_with_ffmpeg(path: Path) -> bool:
    """
    解密出来的 FLAC 尾部会带着 QQ 音乐加密时的填充（≤9KB 垃圾），
    解码器会报 1 个尾部错误。用 ffmpeg 无损重封装一遍，得到 0 error 的干净文件。
    无损（FLAC→PCM→FLAC），音质不变。
    """
    import shutil
    import subprocess
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    tmp = path.with_name(path.name + ".trim.flac")
    try:
        r = subprocess.run(
            [exe, "-v", "error", "-y", "-i", str(path),
             "-c:a", "flac", "-compression_level", "6", str(tmp)],
            capture_output=True, timeout=7200)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
            return False
        os.replace(tmp, path)
        return True
    except Exception:
        return False
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def cmd_findkeys(args):
    files = collect_files(args.targets)
    if not files:
        print("没找到可处理的加密文件", file=sys.stderr)
        return 1
    metas = {f: parse_file(f) for f in files}
    probes = {str(f): (prepare_probe(f, metas[f]), metas[f]["audio_size"]) for f in files}
    hits = scan_memory_for_keys(probes)
    for f in files:
        ek = hits.get(str(f))
        if ek:
            save_cached_ekey(metas[f], ek)
            print(f"[+] {f.name}  song_mid={metas[f]['song_mid']}")
            print(f"    ekey = {ek}")
        else:
            print(f"[ ] {f.name}  未命中")
    if args.out:
        Path(args.out).write_text(
            "\n".join(f"{Path(f).name}\t{hits.get(str(f), '')}" for f in files),
            encoding="utf-8")
        print(f"已写入 {args.out}")
    return 0


def cmd_grabkeys(args):
    files = collect_files(args.targets)
    if not files:
        print("没找到可处理的加密文件", file=sys.stderr)
        return 1
    metas = {f: parse_file(f) for f in files}
    got = grab_keys_from_client(files, metas, timeout=args.timeout)
    ok = 0
    for f in files:
        k = got.get(f.name.lower())
        if not k:
            print(f"[ ] {f.name}  未抓到 key")
            continue
        if not key_fits_file(f, metas[f], k):
            print(f"[!] {f.name}  抓到 key 但解不开（{len(k)}B），可能属于别的文件")
            continue
        ok += 1
        save_cached_rawkey(metas[f], k)
        print(f"[+] {f.name}  key {len(k)}B  song_mid={metas[f]['song_mid']}")
        print(f"    {k.hex()}")
    print(f"\n抓到 {ok}/{len(files)} 个 key，已缓存到 {EKEY_DIR}")
    return 0 if ok == len(files) else 2


def cmd_doctor(args):
    print(f"qmc-unlock {VERSION}")
    print(f"  Python      : {sys.version.split()[0]}  ({sys.platform})")
    lib = load_caccel()
    if lib:
        print(f"  C 加速      : 可用  {CACCEL_DIR}")
    else:
        print(f"  C 加速      : 不可用（找不到 gcc，纯 Python 会慢约 40 倍）")
    pids = find_qqmusic_pids()
    print(f"  QQMusic.exe : {'PID ' + ','.join(map(str, pids)) if pids else '未运行'}")
    n_ekey = n_key = 0
    if EKEY_DIR.exists():
        n_ekey = len(list(EKEY_DIR.glob("*.txt")))
        n_key = len(list(EKEY_DIR.glob("*.key")))
    print(f"  key 缓存    : {EKEY_DIR}  (ekey {n_ekey} 条 / 流key {n_key} 条)")
    n = 0
    for t in args.targets or []:
        n += len(collect_files([t]))
    if args.targets:
        print(f"  目标文件    : {n} 个")
    return 0


# ─────────────────────────── main ───────────────────────────

def main():
    ap = argparse.ArgumentParser(
        prog="qmc_unlock",
        description="离线 QQ 音乐加密音频解锁（mflac/mgg/qmc*）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python qmc_unlock.py info "D:\\Music\\VipSongsDownload"
  python qmc_unlock.py decrypt "D:\\Music\\VipSongsDownload" -o out --from-memory
  python qmc_unlock.py decrypt song.mflac --ekey "AA...==" -o out
  python qmc_unlock.py findkeys "D:\\Music\\VipSongsDownload" -o keys.txt
""")
    ap.add_argument("-v", "--version", action="version", version=f"qmc-unlock {VERSION}")
    sub = ap.add_subparsers(dest="cmd")

    p_info = sub.add_parser("info", help="查看文件格式 / song_mid / key 状态")
    p_info.add_argument("targets", nargs="+")
    p_info.add_argument("--ekey-dir", action="append", default=[])
    p_info.add_argument("--json", action="store_true")
    p_info.set_defaults(func=cmd_info)

    p_dec = sub.add_parser("decrypt", help="解密（批量/目录）")
    p_dec.add_argument("targets", nargs="+")
    p_dec.add_argument("-o", "--out", help="输出目录")
    p_dec.add_argument("--ekey", help="base64 ekey（服务端下发的那种）")
    p_dec.add_argument("--key-hex", help="直接给派生后的 QMC 流 key（hex 或 base64）")
    p_dec.add_argument("--key-file", help="从文件读流 key（hex/base64）")
    p_dec.add_argument("--ekey-dir", action="append", default=[], help="额外 key 目录（<songmid>.txt / .key）")
    p_dec.add_argument("--from-client", action="store_true", help="用 frida 从 QQ 音乐客户端抓流 key")
    p_dec.add_argument("--auto-client", action="store_true", help="缓存没有时自动从客户端抓")
    p_dec.add_argument("--from-memory", action="store_true", help="从 QQMusic.exe 内存暴力找 ekey")
    p_dec.add_argument("--auto-memory", action="store_true", help="缓存里没有时自动扫内存")
    p_dec.add_argument("--trim", action="store_true", help="解密后用 ffmpeg 无损重封装，去掉尾部加密填充（得到 0 error 的干净 FLAC）")
    p_dec.add_argument("--overwrite", action="store_true")
    p_dec.add_argument("--json", action="store_true")
    p_dec.set_defaults(func=cmd_decrypt)

    p_ck = sub.add_parser("grabkeys", help="只抓 key（从 QQ 音乐客户端），不做解密")
    p_ck.add_argument("targets", nargs="+")
    p_ck.add_argument("--timeout", type=int, default=18, help="每个文件最多等多少秒")
    p_ck.set_defaults(func=cmd_grabkeys)

    p_fk = sub.add_parser("findkeys", help="扫描 QQMusic.exe 内存，列出各文件的 ekey")
    p_fk.add_argument("targets", nargs="+")
    p_fk.add_argument("-o", "--out", help="结果写入文件")
    p_fk.set_defaults(func=cmd_findkeys)

    p_doc = sub.add_parser("doctor", help="环境自检")
    p_doc.add_argument("targets", nargs="*")
    p_doc.set_defaults(func=cmd_doctor)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
