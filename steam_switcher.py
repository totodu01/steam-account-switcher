#!/usr/bin/env python3

from __future__ import annotations

import sys
import os
import re
import zlib
import json
import base64
import ctypes
import ctypes.wintypes as wintypes
import winreg
import subprocess
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QLineEdit, QDialog,
    QPlainTextEdit, QMessageBox, QMenu, QInputDialog, QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QSize, QRect, QPoint
from PyQt6.QtGui import (
    QPixmap, QIcon, QFont, QColor, QPainter, QPainterPath,
    QBrush, QPen, QCursor, QLinearGradient,
)

# ─── Palette (Steam dark theme) ───────────────────────────────────────────────

BG          = "#171d25"   # main window background
SURFACE     = "#1b2838"   # header / footer panels
CARD        = "#1e2d3d"   # account card
CARD_HOVER  = "#243649"   # card on hover
ACCENT      = "#66c0f4"   # Steam blue
ACCENT_DARK = "#4a9fc8"   # pressed/darker accent
TEXT        = "#c6d4df"   # primary text
MUTED       = "#8f98a0"   # secondary / label text
BORDER      = "#2d4057"   # dividers and borders
SUCCESS     = "#a4d007"   # positive (prime, medal…)
DANGER      = "#c94e3c"   # negative (vac, cooldown…)
NEW_BADGE   = "#4c7a22"   # "NEW" placeholder badge
MONEY_CLR   = "#e05a4b"   # inventory value (red, matching screenshot)

AVATAR_SIZE = 46
CARD_H      = 70

# Details popup: ordered list of (token_key, display_label, value_type)
# value_type: "money" | "number" | "bool" | "vac"
_DETAIL_FIELDS = [
    ("inventoryValue",     "Inventory",      "money"),
    ("rating",             "Rating",         "number"),
    ("csgoRank",           "CS:GO Rank",     "number"),
    ("earnedServiceMedal", "Service Medal",  "bool"),
    ("medals",             "Medal Count",    "number"),
    ("hasRareItem",        "Rare Items",     "number"),
    ("vacStatus",          "VAC Status",     "vac"),
    ("primeStatus",        "Prime Status",   "bool"),
    ("cooldown",           "Cooldown",       "vac"),
]


# ─── VDF parser ───────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list:
    tokens, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '/' and i + 1 < n and text[i + 1] == '/':
            while i < n and text[i] != '\n':
                i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n:
                if text[i] == '\\' and i + 1 < n:
                    buf.append(text[i + 1]); i += 2
                elif text[i] == '"':
                    i += 1; break
                else:
                    buf.append(text[i]); i += 1
            tokens.append(('s', ''.join(buf)))
        elif c in '{}':
            tokens.append(('b', c)); i += 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}':
                j += 1
            tokens.append(('s', text[i:j])); i = j
    return tokens


def _parse_block(tokens: list, pos: int) -> tuple[dict, int]:
    result: dict = {}
    while pos < len(tokens):
        kind, val = tokens[pos]
        if kind == 'b' and val == '}':
            return result, pos + 1
        if kind == 's':
            key = val; pos += 1
            if pos >= len(tokens):
                break
            k2, v2 = tokens[pos]
            if k2 == 'b' and v2 == '{':
                child, pos = _parse_block(tokens, pos + 1)
                result[key] = child
            else:
                result[key] = v2; pos += 1
        else:
            pos += 1
    return result, pos


def parse_vdf(text: str) -> dict:
    tokens = _tokenize(text)
    pos = 0
    if pos < len(tokens) and tokens[pos][0] == 's':
        pos += 1                         # skip root key name
    if pos < len(tokens) and tokens[pos] == ('b', '{'):
        pos += 1
    result, _ = _parse_block(tokens, pos)
    return result


# ─── Steam path ───────────────────────────────────────────────────────────────

def get_steam_path() -> Path:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam")
    path, _ = winreg.QueryValueEx(key, "SteamPath")
    winreg.CloseKey(key)
    return Path(path)


def get_loginusers_path() -> Path:
    return get_steam_path() / "config" / "loginusers.vdf"


def parse_loginusers() -> dict:
    path = get_loginusers_path()
    if not path.exists():
        return {}
    return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))


def find_avatar(steam_path: Path, steamid: str) -> Optional[QPixmap]:
    cache = steam_path / "config" / "avatarcache"
    for suffix in (".png", ".jpg", "_full.png", "_medium.jpg"):
        p = cache / f"{steamid}{suffix}"
        if p.exists():
            px = QPixmap(str(p))
            if not px.isNull():
                return px
    return None


# ─── Avatar helpers ───────────────────────────────────────────────────────────

def _rounded(px: QPixmap, r: int = 8) -> QPixmap:
    out = QPixmap(px.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(px.width()), float(px.height()), r, r)
    p.setClipPath(path)
    p.drawPixmap(0, 0, px)
    p.end()
    return out


def _letter_avatar(letter: str, seed: str, size: int = AVATAR_SIZE) -> QPixmap:
    hue = (hash(seed) % 360 + 360) % 360
    color = QColor.fromHsv(hue, 160, 190)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 8, 8)
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", size // 3, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter.upper())
    p.end()
    return px


def _new_badge(size: int = AVATAR_SIZE) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(NEW_BADGE)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 8, 8)
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", size // 4, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "NEW")
    p.end()
    return px


# ─── DPAPI / crypto ───────────────────────────────────────────────────────────

class _BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]

# Declare argtypes once so ctypes uses the right sizes on 64-bit Windows.
_CryptProtectData = ctypes.windll.crypt32.CryptProtectData
_CryptProtectData.restype  = wintypes.BOOL
_CryptProtectData.argtypes = [
    ctypes.POINTER(_BLOB),   # pDataIn
    ctypes.c_wchar_p,        # szDataDescr
    ctypes.POINTER(_BLOB),   # pOptionalEntropy
    ctypes.c_void_p,         # pvReserved
    ctypes.c_void_p,         # pPromptStruct
    wintypes.DWORD,          # dwFlags
    ctypes.POINTER(_BLOB),   # pDataOut
]


def _dpapi_protect(data: bytes, entropy: bytes) -> bytes:
    buf_d = (ctypes.c_ubyte * len(data))(*data)
    buf_e = (ctypes.c_ubyte * len(entropy))(*entropy)
    blob_in  = _BLOB(len(data),    buf_d)
    blob_ent = _BLOB(len(entropy), buf_e)
    blob_out = _BLOB()
    ok = _CryptProtectData(
        ctypes.byref(blob_in),
        "ObfuscateBuffer",
        ctypes.byref(blob_ent),
        None, None,
        0x11,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise RuntimeError(f"CryptProtectData failed (error {ctypes.GetLastError()})")
    result = bytes(bytearray(blob_out.pbData[:blob_out.cbData]))
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return result


def _steam_encrypt(token: str, account_name: str) -> str:
    return _dpapi_protect(token.encode(), account_name.encode()).hex()


def _crc32_key(name: str) -> str:
    v = zlib.crc32(name.encode()) & 0xFFFFFFFF
    h = format(v, "08x").lstrip("0") or "0"
    return h + "1"


def _jwt_steamid(jwt: str) -> str:
    parts = jwt.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT (expected 3 parts separated by '.')")
    pad = 4 - len(parts[1]) % 4
    payload = base64.urlsafe_b64decode(parts[1] + "=" * pad)
    sub = json.loads(payload).get("sub")
    if not sub:
        raise ValueError("JWT missing 'sub' field (SteamID)")
    return sub


def _steamid3(steamid64: str) -> str:
    n = int(steamid64)
    if n < 76561197960265728:
        raise ValueError("SteamID64 value is too small")
    return str(n - 76561197960265728)


def _timestamp() -> str:
    return str(int(time.time()))


# ─── Steam process ────────────────────────────────────────────────────────────

def kill_steam():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"SOFTWARE\Valve\Steam\ActiveProcess")
        pid, _ = winreg.QueryValueEx(key, "pid")
        winreg.CloseKey(key)
        if pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"],
                           capture_output=True)
            time.sleep(1)
    except Exception:
        pass


def _set_autologin(account_name: str):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam",
                         access=winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "AutoLoginUser", 0, winreg.REG_SZ, account_name)
    winreg.CloseKey(key)


# ─── VDF file writers ─────────────────────────────────────────────────────────

def _inject_config_vdf(path: Path, username: str, steamid: str):
    content = path.read_text(encoding="utf-8", errors="replace")
    if f'"SteamID"\t\t"{steamid}"' in content:
        return
    block = (
        f'\n\t\t\t\t\t"{username}"\n'
        f'\t\t\t\t\t{{\n'
        f'\t\t\t\t\t\t"SteamID"\t\t"{steamid}"\n'
        f'\t\t\t\t\t}}\n'
    )
    idx = content.rfind('"Accounts"')
    if idx == -1:
        return
    brace = content.find('{', idx)
    if brace == -1:
        return
    path.write_text(content[:brace + 1] + block + content[brace + 1:],
                    encoding="utf-8")


def _reset_most_recent(content: str) -> str:
    return re.sub(r'"MostRecent"(\s+)"1"', r'"MostRecent"\g<1>"0"', content)


def _insert_user(content: str, username: str, steamid: str) -> str:
    block = (
        f'\n\t"{steamid}"\n'
        f'\t{{\n'
        f'\t\t"AccountName"\t\t"{username}"\n'
        f'\t\t"PersonaName"\t\t"{username}"\n'
        f'\t\t"RememberPassword"\t\t"1"\n'
        f'\t\t"WantsOfflineMode"\t\t"0"\n'
        f'\t\t"SkipOfflineModeWarning"\t\t"0"\n'
        f'\t\t"AllowAutoLogin"\t\t"1"\n'
        f'\t\t"MostRecent"\t\t"1"\n'
        f'\t\t"Timestamp"\t\t"{_timestamp()}"\n'
        f'\t}}\n'
    )
    pos = content.rfind('}')
    return content[:pos] + block + content[pos:]


def _update_user(content: str, username: str, steamid: str) -> str:
    lines = content.splitlines(keepends=True)
    out, in_user, depth = [], False, 0
    ts = _timestamp()
    for line in lines:
        t = line.strip()
        if t == f'"{steamid}"':
            in_user = True; depth = 0; out.append(line); continue
        if in_user:
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0:
                    in_user = False
            if '"AccountName"' in t:
                out.append(f'\t\t"AccountName"\t\t"{username}"\n'); continue
            if '"PersonaName"' in t:
                out.append(f'\t\t"PersonaName"\t\t"{username}"\n'); continue
            if '"MostRecent"' in t:
                out.append('\t\t"MostRecent"\t\t"1"\n'); continue
            if '"Timestamp"' in t:
                out.append(f'\t\t"Timestamp"\t\t"{ts}"\n'); continue
        out.append(line)
    return ''.join(out)


def _set_most_recent_only(content: str, steamid: str) -> str:
    lines = content.splitlines(keepends=True)
    out, in_user, depth = [], False, 0
    for line in lines:
        t = line.strip()
        if t == f'"{steamid}"':
            in_user = True; depth = 0
        if in_user:
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0:
                    in_user = False
            if '"MostRecent"' in t:
                out.append('\t\t"MostRecent"\t\t"1"\n'); continue
        out.append(line)
    return ''.join(out)


def _write_local_vdf(username: str, token: str):
    crc = _crc32_key(username)
    enc = _steam_encrypt(token, username)
    base = Path(os.environ["LOCALAPPDATA"]) / "Steam"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "local.vdf"

    if path.exists():
        content = path.read_text(encoding="utf-8", errors="replace")
        content = _inject_connect_cache(content, crc, enc)
    else:
        content = _new_local_vdf(crc, enc)
    path.write_text(content, encoding="utf-8")


def _inject_connect_cache(content: str, crc: str, enc: str) -> str:
    lines = content.splitlines(keepends=True)
    out, in_cc, depth, replaced = [], False, 0, False
    for line in lines:
        t = line.strip()
        if t == '"ConnectCache"':
            in_cc = True; depth = 0; out.append(line); continue
        if in_cc:
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0 and not replaced:
                    out.append(f'\t\t\t\t\t"{crc}"\t\t"{enc}"\n')
                    replaced = True
            if t.startswith(f'"{crc}"'):
                out.append(f'\t\t\t\t\t"{crc}"\t\t"{enc}"\n')
                replaced = True; continue
        out.append(line)
    if not replaced:
        raise RuntimeError("ConnectCache block not found in local.vdf")
    return ''.join(out)


def _new_local_vdf(crc: str, enc: str) -> str:
    return (
        '"MachineUserConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"ConnectCache"\n\t\t\t\t{\n'
        f'\t\t\t\t\t"{crc}"\t\t"{enc}"\n'
        '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
    )


def _write_localconfig_vdf(steamid64: str):
    sid3 = _steamid3(steamid64)
    content = (
        '"UserLocalConfigStore"\n{\n'
        '\t"friends"\n\t{\n'
        '\t\t"SignIntoFriends" "1"\n'
        '\t}\n}\n'
    )
    path = (Path("C:/Program Files (x86)/Steam") / "userdata"
            / sid3 / "config" / "localconfig.vdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ─── Extra account data (persisted next to the script) ───────────────────────

_EXTRA_PATH = Path(__file__).parent / "accounts_extra.json"


def _load_extra() -> dict:
    try:
        return json.loads(_EXTRA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_extra(data: dict):
    _EXTRA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_extra_fields(parts: list[str]) -> dict:
    """Parse parts[2:] of a token string into a key→value dict."""
    extra: dict = {}
    for chunk in parts[2:]:
        chunk = chunk.strip()
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            extra[k.strip()] = v.strip()
    return extra


# ─── High-level operations ────────────────────────────────────────────────────

def add_account(token_str: str) -> str:
    token_str = token_str.strip()
    if "----" not in token_str:
        raise ValueError("Invalid format — expected:  username----eyJ…")
    parts    = token_str.split("----")
    username = parts[0].strip()
    jwt      = parts[1].strip() if len(parts) > 1 else ""
    if not username or not jwt:
        raise ValueError("Username or token is empty")

    steamid    = _jwt_steamid(jwt)
    steam_path = get_steam_path()
    config_dir = steam_path / "config"
    config_vdf = config_dir / "config.vdf"
    lu_vdf     = config_dir / "loginusers.vdf"

    if not config_vdf.exists() or not lu_vdf.exists():
        raise RuntimeError(
            "Steam config files not found.\n"
            "Open Steam and log in to any account first."
        )

    kill_steam()
    _inject_config_vdf(config_vdf, username, steamid)

    content = lu_vdf.read_text(encoding="utf-8", errors="replace")
    content = _reset_most_recent(content)
    if f'"{steamid}"' in content:
        content = _update_user(content, username, steamid)
    else:
        content = _insert_user(content, username, steamid)
    lu_vdf.write_text(content, encoding="utf-8")

    _write_local_vdf(username, jwt)
    _write_localconfig_vdf(steamid)
    _set_autologin(username)

    # Persist any extra fields that came after the token
    extra = _parse_extra_fields(parts)
    if extra:
        store = _load_extra()
        store[steamid] = extra
        _save_extra(store)

    return f"Account '{username}' added successfully."


def launch_account(username: str, steamid: str):
    kill_steam()
    _set_autologin(username)

    lu_path = get_loginusers_path()
    content = lu_path.read_text(encoding="utf-8", errors="replace")
    content = _reset_most_recent(content)
    content = _set_most_recent_only(content, steamid)
    lu_path.write_text(content, encoding="utf-8")

    steam_exe = get_steam_path() / "steam.exe"
    subprocess.Popen([str(steam_exe)])


def delete_account(steamid: str):
    lu_path = get_loginusers_path()
    content = lu_path.read_text(encoding="utf-8", errors="replace")

    lines = content.splitlines(keepends=True)
    out, skip, depth = [], False, 0
    i = 0
    while i < len(lines):
        t = lines[i].strip()
        if t == f'"{steamid}"':
            skip = True; depth = 0; i += 1; continue
        if skip:
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0:
                    skip = False; i += 1; continue
            i += 1; continue
        out.append(lines[i]); i += 1

    lu_path.write_text(''.join(out), encoding="utf-8")

    store = _load_extra()
    if steamid in store:
        del store[steamid]
        _save_extra(store)


def rename_persona(steamid: str, new_name: str):
    lu_path = get_loginusers_path()
    content = lu_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    out, in_user, depth = [], False, 0
    for line in lines:
        t = line.strip()
        if t == f'"{steamid}"':
            in_user = True; depth = 0
        if in_user:
            if t == '{':
                depth += 1
            elif t == '}':
                depth -= 1
                if depth == 0:
                    in_user = False
            if '"PersonaName"' in t:
                out.append(f'\t\t"PersonaName"\t\t"{new_name}"\n'); continue
        out.append(line)
    lu_path.write_text(''.join(out), encoding="utf-8")


def clear_steam():
    steam_path = get_steam_path()
    kill_steam()
    for fname in ("config.vdf", "loginusers.vdf"):
        p = steam_path / "config" / fname
        if p.exists():
            p.unlink()
    local = Path(os.environ["LOCALAPPDATA"]) / "Steam"
    if local.exists():
        shutil.rmtree(local, ignore_errors=True)


# ─── Shared stylesheet helpers ────────────────────────────────────────────────

def _btn(bg: str, hover: str, color: str = "white",
         size: int = 12, radius: int = 6) -> str:
    return (
        f"QPushButton {{"
        f"background:{bg};color:{color};border:none;"
        f"border-radius:{radius}px;padding:0 14px;"
        f"font-size:{size}px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{bg};}}"
    )


# ─── Details popup ────────────────────────────────────────────────────────────

def _is_truthy(v: str) -> bool:
    return v.strip().lower() in ("yes", "true", "1")


def _fmt_value(raw: str, kind: str) -> tuple[str, str]:
    """Return (display_text, color)."""
    v = raw.strip()
    if kind == "money":
        try:
            display = f"${float(v):.2f}"
        except ValueError:
            display = v
        return display, MONEY_CLR
    if kind == "bool":
        return v, (SUCCESS if _is_truthy(v) else MUTED)
    if kind == "vac":
        # True/Yes = bad (banned/on cooldown)
        return v, (DANGER if _is_truthy(v) else SUCCESS)
    return v, TEXT   # "number" or anything else


class DetailsDialog(QDialog):
    def __init__(self, persona: str, extra: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Account Details")
        self.setFixedWidth(300)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog   {{ background:{SURFACE}; }}
            QLabel    {{ background:transparent; font-family:'Segoe UI',Arial; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Section header ────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(f"background:#16202d;border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)

        hdr_lbl = QLabel("DETAILS")
        hdr_lbl.setStyleSheet(
            f"color:{MUTED};font-size:10px;font-weight:bold;letter-spacing:1px;"
        )
        persona_lbl = QLabel(persona)
        persona_lbl.setStyleSheet(
            f"color:{TEXT};font-size:11px;"
        )
        persona_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        hl.addWidget(hdr_lbl)
        hl.addStretch()
        hl.addWidget(persona_lbl)
        root.addWidget(hdr)

        # ── Rows ──────────────────────────────────────────────────────────────
        rows_widget = QWidget()
        rows_widget.setStyleSheet(f"background:{SURFACE};")
        rows_lay = QVBoxLayout(rows_widget)
        rows_lay.setContentsMargins(0, 0, 0, 0)
        rows_lay.setSpacing(0)

        shown = 0
        for idx, (key, label, kind) in enumerate(_DETAIL_FIELDS):
            if key not in extra:
                continue
            raw = extra[key]
            display, color = _fmt_value(raw, kind)

            row = QWidget()
            # Alternating row shade
            row_bg = CARD if idx % 2 == 0 else SURFACE
            row.setStyleSheet(f"background:{row_bg};")
            row.setFixedHeight(34)

            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 0, 16, 0)

            key_lbl = QLabel(label)
            key_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")

            val_lbl = QLabel(display)
            val_lbl.setStyleSheet(
                f"color:{color};font-size:12px;font-weight:600;"
            )
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            rl.addWidget(key_lbl)
            rl.addStretch()
            rl.addWidget(val_lbl)
            rows_lay.addWidget(row)
            shown += 1

        if shown == 0:
            empty = QLabel("No extra data available for this account.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{MUTED};font-size:12px;padding:20px;")
            rows_lay.addWidget(empty)

        root.addWidget(rows_widget)

        # ── Close button ──────────────────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(46)
        footer.setStyleSheet(f"background:#16202d;border-top:1px solid {BORDER};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 6, 14, 6)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(30)
        close_btn.setStyleSheet(_btn(ACCENT, ACCENT_DARK, size=11))
        close_btn.clicked.connect(self.accept)
        fl.addStretch()
        fl.addWidget(close_btn)
        root.addWidget(footer)

        # Auto-fit height
        self.adjustSize()


# ─── Add Account dialog ───────────────────────────────────────────────────────

class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Account")
        self.setFixedSize(460, 210)
        self.setStyleSheet(f"""
            QDialog  {{ background:{SURFACE}; }}
            QLabel   {{ color:{TEXT}; font-size:13px; background:transparent; }}
            QPlainTextEdit {{
                background:{CARD}; color:{TEXT};
                border:1px solid {BORDER}; border-radius:6px;
                padding:8px; font-family:Consolas,monospace; font-size:11px;
            }}
            QPlainTextEdit:focus {{ border-color:{ACCENT}; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)

        title = QLabel("Paste your account token")
        title.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:bold;background:transparent;")
        lay.addWidget(title)

        hint = QLabel(f'<span style="color:{MUTED}">Format: </span>'
                      f'<span style="color:{TEXT}">username</span>'
                      f'<span style="color:{ACCENT}">----</span>'
                      f'<span style="color:{MUTED}">eyJhbGci…</span>')
        hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(hint)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("Paste here…")
        self._edit.setFixedHeight(68)
        lay.addWidget(self._edit)

        row = QHBoxLayout()
        row.setSpacing(8)

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(34)
        cancel.setStyleSheet(_btn(BORDER, CARD, MUTED))
        cancel.clicked.connect(self.reject)

        ok = QPushButton("Add Account")
        ok.setFixedHeight(34)
        ok.setStyleSheet(_btn(ACCENT, ACCENT_DARK))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)

        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def token(self) -> str:
        return self._edit.toPlainText().strip()


# ─── Account card ─────────────────────────────────────────────────────────────

class AccountCard(QFrame):
    sig_launch = None   # connected per-instance
    sig_delete = None
    sig_rename = None
    sig_copy   = None

    def __init__(self, steamid: str, data: dict,
                 steam_path: Path, extra: dict | None = None, parent=None):
        super().__init__(parent)
        self.steamid    = steamid
        self.data       = data
        self.steam_path = steam_path
        self._extra     = extra or {}

        username = data.get("AccountName", steamid)
        persona  = data.get("PersonaName", username)
        ts_raw   = data.get("Timestamp", "0")
        is_new   = (not persona or persona == username or persona == steamid)

        self.setFixedHeight(CARD_H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)
        self._paint_bg(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(12)

        # ── Avatar ──────────────────────────────────────────────────────────
        av_lbl = QLabel()
        av_lbl.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        av_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        px = find_avatar(steam_path, steamid)
        if px:
            px = px.scaled(AVATAR_SIZE, AVATAR_SIZE,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            av_lbl.setPixmap(_rounded(px, 8))
        elif is_new:
            av_lbl.setPixmap(_new_badge())
        else:
            av_lbl.setPixmap(_letter_avatar(persona[0], steamid))

        lay.addWidget(av_lbl)

        # ── Names ────────────────────────────────────────────────────────────
        name_lay = QVBoxLayout()
        name_lay.setSpacing(2)
        name_lay.setContentsMargins(0, 0, 0, 0)

        p_lbl = QLabel(persona if persona else steamid)
        p_lbl.setStyleSheet(
            f"color:{TEXT};font-size:13px;font-weight:600;background:transparent;"
        )
        u_lbl = QLabel(username)
        u_lbl.setStyleSheet(
            f"color:{MUTED};font-size:11px;background:transparent;"
        )

        name_lay.addWidget(p_lbl)
        name_lay.addWidget(u_lbl)
        lay.addLayout(name_lay)
        lay.addStretch()

        # ── Timestamp ────────────────────────────────────────────────────────
        try:
            ts = int(ts_raw)
            ts_str = datetime.fromtimestamp(ts).strftime("%d.%m.%Y  %H:%M") if ts else ""
        except Exception:
            ts_str = ""

        if ts_str:
            ts_lbl = QLabel(ts_str)
            ts_lbl.setStyleSheet(
                f"color:{MUTED};font-size:11px;background:transparent;"
            )
            ts_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lay.addWidget(ts_lbl)

        # ── Launch button ─────────────────────────────────────────────────────
        launch_btn = QPushButton("Launch")
        launch_btn.setFixedSize(68, 30)
        launch_btn.setStyleSheet(_btn(ACCENT, ACCENT_DARK, size=11))
        launch_btn.clicked.connect(
            lambda: self._emit_launch(username, steamid)
        )
        lay.addWidget(launch_btn)

        self._username = username
        self._persona  = persona

        self._cb_launch: list = []
        self._cb_delete: list = []
        self._cb_rename: list = []
        self._cb_copy:   list = []

    def on_launch(self, cb): self._cb_launch.append(cb)
    def on_delete(self, cb): self._cb_delete.append(cb)
    def on_rename(self, cb): self._cb_rename.append(cb)
    def on_copy(self,   cb): self._cb_copy.append(cb)

    def _emit_launch(self, u, s):
        for cb in self._cb_launch: cb(u, s)

    def mousePressEvent(self, event):
        # Left-click anywhere on the card body (not on child buttons) → details
        if event.button() == Qt.MouseButton.LeftButton:
            dlg = DetailsDialog(self._persona, self._extra, self)
            dlg.exec()
        super().mousePressEvent(event)

    def _paint_bg(self, hovered: bool):
        bg = CARD_HOVER if hovered else CARD
        self.setStyleSheet(
            f"AccountCard{{background:{bg};border-radius:8px;"
            f"border:1px solid {BORDER};}}"
        )

    def enterEvent(self, e):  self._paint_bg(True);  super().enterEvent(e)
    def leaveEvent(self, e):  self._paint_bg(False); super().leaveEvent(e)

    def _ctx(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background:{CARD};color:{TEXT};
                border:1px solid {BORDER};border-radius:6px;padding:4px;
            }}
            QMenu::item {{ padding:7px 18px;border-radius:4px; }}
            QMenu::item:selected {{ background:{ACCENT}; }}
            QMenu::separator {{ background:{BORDER};height:1px;margin:3px 10px; }}
        """)

        a_launch = menu.addAction("▶  Launch Account")
        menu.addSeparator()
        a_copy   = menu.addAction("⎘  Copy SteamID64")
        a_rename = menu.addAction("✎  Change Persona Name")
        menu.addSeparator()
        a_delete = menu.addAction("🗑  Delete Account")

        action = menu.exec(self.mapToGlobal(pos))
        if action == a_launch:
            self._emit_launch(self._username, self.steamid)
        elif action == a_copy:
            for cb in self._cb_copy:   cb(self.steamid)
        elif action == a_rename:
            for cb in self._cb_rename: cb(self.steamid, self._persona)
        elif action == a_delete:
            for cb in self._cb_delete: cb(self.steamid)


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam Account Switcher")
        self.setMinimumSize(500, 400)
        self.resize(500, 580)

        _ico = Path(__file__).parent / "rsc" / "ico.ico"
        if _ico.exists():
            self.setWindowIcon(QIcon(str(_ico)))

        try:
            self._steam = get_steam_path()
        except Exception:
            self._steam = Path("C:/Program Files (x86)/Steam")

        # Global stylesheet (affects QMessageBox / QInputDialog too)
        self.setStyleSheet(f"""
            * {{ font-family:'Segoe UI',Arial,sans-serif; }}
            QMainWindow, QWidget {{ background:{BG}; color:{TEXT}; }}
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{
                background:{SURFACE};width:5px;border-radius:3px;
            }}
            QScrollBar::handle:vertical {{
                background:{BORDER};border-radius:3px;min-height:20px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
            QMessageBox {{ background:{SURFACE}; }}
            QInputDialog {{ background:{SURFACE}; }}
            QInputDialog QLineEdit {{
                background:{CARD};color:{TEXT};
                border:1px solid {BORDER};border-radius:6px;padding:6px 10px;
            }}
            QInputDialog QPushButton {{ {_btn(ACCENT, ACCENT_DARK)} }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(54)
        hdr.setStyleSheet(
            f"background:{SURFACE};border-bottom:1px solid {BORDER};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(8)

        self._add_btn = QPushButton("＋  Add Account")
        self._add_btn.setFixedHeight(34)
        self._add_btn.setStyleSheet(_btn(ACCENT, ACCENT_DARK))
        self._add_btn.clicked.connect(self._do_add)

        self._clear_btn = QPushButton("Clear Steam")
        self._clear_btn.setFixedHeight(34)
        self._clear_btn.setStyleSheet(_btn("#2d4057", "#3a5068", MUTED))
        self._clear_btn.clicked.connect(self._do_clear)

        hl.addWidget(self._add_btn)
        hl.addWidget(self._clear_btn)
        hl.addStretch()
        root.addWidget(hdr)

        # ── Search row ───────────────────────────────────────────────────────
        sr = QWidget()
        sr.setFixedHeight(46)
        sr.setStyleSheet(f"background:{BG};")
        sl = QHBoxLayout(sr)
        sl.setContentsMargins(14, 7, 14, 7)
        sl.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search accounts…")
        self._search.setFixedHeight(30)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background:{SURFACE};color:{TEXT};
                border:1px solid {BORDER};border-radius:6px;
                padding:0 10px;font-size:12px;
            }}
            QLineEdit:focus {{ border-color:{ACCENT}; }}
        """)
        self._search.textChanged.connect(self._filter)

        reload_btn = QPushButton("Reload")
        reload_btn.setFixedSize(62, 30)
        reload_btn.setStyleSheet(_btn("#2d4057", "#3a5068", MUTED, 11))
        reload_btn.clicked.connect(self.load)

        sl.addWidget(self._search)
        sl.addWidget(reload_btn)
        root.addWidget(sr)

        # ── Account list ─────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._list_w = QWidget()
        self._list_w.setStyleSheet(f"background:{BG};")
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(10, 8, 10, 8)
        self._list_lay.setSpacing(5)
        self._list_lay.addStretch()

        self._scroll.setWidget(self._list_w)
        root.addWidget(self._scroll)

        # ── Status bar ───────────────────────────────────────────────────────
        self._status = QLabel("")
        self._status.setFixedHeight(26)
        self._status.setStyleSheet(
            f"background:{SURFACE};color:{MUTED};font-size:11px;"
            f"padding:0 14px;border-top:1px solid {BORDER};"
        )
        root.addWidget(self._status)

        self._cards: list[AccountCard] = []
        self._accounts: dict           = {}
        self.load()

    # ── Loaders ──────────────────────────────────────────────────────────────

    def load(self):
        for c in self._cards:
            c.deleteLater()
        self._cards.clear()
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            users = parse_loginusers()
        except Exception as e:
            self._st(f"Error: {e}", DANGER)
            return

        self._accounts = users
        extra_all = _load_extra()

        if not users:
            ph = QLabel("No accounts found. Click '＋ Add Account' to begin.")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setStyleSheet(f"color:{MUTED};font-size:13px;")
            self._list_lay.insertWidget(0, ph)
            self._st("No accounts")
            return

        sorted_ids = sorted(
            users.keys(),
            key=lambda sid: int(users[sid].get("Timestamp", "0") or "0"),
            reverse=True,
        )

        for idx, steamid in enumerate(sorted_ids):
            card = AccountCard(steamid, users[steamid], self._steam,
                               extra=extra_all.get(steamid, {}))
            card.on_launch(self._do_launch)
            card.on_delete(self._do_delete)
            card.on_rename(self._do_rename)
            card.on_copy(self._do_copy)
            self._list_lay.insertWidget(idx, card)
            self._cards.append(card)

        n = len(users)
        self._st(f"{n} account{'s' if n != 1 else ''}")

    def _filter(self, text: str):
        t = text.lower()
        for card in self._cards:
            show = (
                not t
                or t in card.data.get("AccountName", "").lower()
                or t in card.data.get("PersonaName", "").lower()
                or t in card.steamid
            )
            card.setVisible(show)

    def _st(self, msg: str, color: str = MUTED):
        self._status.setStyleSheet(
            f"background:{SURFACE};color:{color};font-size:11px;"
            f"padding:0 14px;border-top:1px solid {BORDER};"
        )
        self._status.setText(msg)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_add(self):
        dlg = AddAccountDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        token = dlg.token()
        if not token:
            return
        try:
            msg = add_account(token)
            self._st(msg, SUCCESS)
            self.load()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self._st(str(e), DANGER)

    def _do_clear(self):
        reply = QMessageBox.question(
            self, "Clear Steam",
            "This will delete Steam config files and stop Steam.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            clear_steam()
            self._st("Steam cleared successfully.", SUCCESS)
        except Exception as e:
            self._st(str(e), DANGER)

    def _do_launch(self, username: str, steamid: str):
        try:
            launch_account(username, steamid)
            self._st(f"Launching Steam as  {username}…", SUCCESS)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self._st(str(e), DANGER)

    def _do_delete(self, steamid: str):
        name = self._accounts.get(steamid, {}).get("AccountName", steamid)
        reply = QMessageBox.question(
            self, "Delete Account",
            f"Remove  '{name}'  from the list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_account(steamid)
            self._st(f"Removed {name}", SUCCESS)
            self.load()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self._st(str(e), DANGER)

    def _do_rename(self, steamid: str, current: str):
        new_name, ok = QInputDialog.getText(
            self, "Change Persona Name", "New persona name:",
            QLineEdit.EchoMode.Normal, current,
        )
        if not ok or not new_name.strip():
            return
        try:
            rename_persona(steamid, new_name.strip())
            self._st("Persona name updated.", SUCCESS)
            self.load()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self._st(str(e), DANGER)

    def _do_copy(self, steamid: str):
        QApplication.clipboard().setText(steamid)
        self._st(f"Copied  {steamid}", SUCCESS)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Steam Account Switcher")
    app.setFont(QFont("Segoe UI", 10))

    _ico_path = Path(__file__).parent / "rsc" / "ico.ico"
    if _ico_path.exists():
        app.setWindowIcon(QIcon(str(_ico_path)))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
