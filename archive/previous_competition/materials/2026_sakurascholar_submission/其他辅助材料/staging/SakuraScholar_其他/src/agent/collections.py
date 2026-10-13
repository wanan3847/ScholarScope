"""
收藏夹、已阅、文件夹、用户认证模块

基于 JSON 文件的轻量存储，供 Web 界面使用。

存储文件（均在 src/data/ 下）：
    collections.json  → 用户收藏夹 + 文件夹
    read_papers.json  → 用户已阅论文
    users.json        → 用户账号（密码 hash）
    paper_cache.json  → 论文元数据缓存
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 数据目录
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_COLLECTIONS_FILE = _DATA_DIR / "collections.json"
_READ_PAPERS_FILE = _DATA_DIR / "read_papers.json"
_USERS_FILE = _DATA_DIR / "users.json"
_PAPER_CACHE_FILE = _DATA_DIR / "paper_cache.json"


# ------------------------------------------------------------------ #
# 通用 IO
# ------------------------------------------------------------------ #

def _read_json(path: Path, default: Any = None) -> Any:
    """安全读取 JSON 文件。"""
    if not path.exists():
        return default if default is not None else {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return default if default is not None else {}
        return json.loads(text)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return default if default is not None else {}


def _write_json(path: Path, data: Any) -> None:
    """安全写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.error("写入 %s 失败: %s", path, e)


# ------------------------------------------------------------------ #
# 论文元数据缓存
# ------------------------------------------------------------------ #

def get_cached_paper(paper_id: str) -> Optional[Dict]:
    """从缓存获取论文元数据。"""
    cache = _read_json(_PAPER_CACHE_FILE, {})
    return cache.get(paper_id)


def _cache_paper_meta(username: Optional[str], paper_id: str, meta: Dict) -> None:
    """缓存论文元数据。"""
    if not meta:
        return
    cache = _read_json(_PAPER_CACHE_FILE, {})
    cache[paper_id] = meta
    _write_json(_PAPER_CACHE_FILE, cache)


# ------------------------------------------------------------------ #
# 收藏夹
# ------------------------------------------------------------------ #

def _get_user_collections(user_id: Optional[str] = None) -> Dict:
    """获取用户收藏数据。"""
    uid = user_id or "web-anonymous"
    data = _read_json(_COLLECTIONS_FILE, {})
    if uid not in data:
        data[uid] = {"papers": {}, "folders": []}
        _write_json(_COLLECTIONS_FILE, data)
    return data[uid]


def _save_user_collections(user_id: str, user_data: Dict) -> None:
    """保存用户收藏数据。"""
    data = _read_json(_COLLECTIONS_FILE, {})
    data[user_id] = user_data
    _write_json(_COLLECTIONS_FILE, data)


def add_favorite(
    user_id: Optional[str],
    paper_id: str,
    paper_meta: Optional[Dict] = None,
    folder_id: Optional[str] = None,
) -> Dict:
    """添加收藏。

    folder_id 语义：
      - 显式传入字符串  → 存入该文件夹（"" 表示未分类）
      - 未传（None）     → 使用用户设置的默认文件夹（未设置则未分类）
    """
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    if folder_id is None:
        # 使用用户默认文件夹；默认文件夹已被删除时回退未分类
        folder_id = uc.get("default_folder_id", "") or ""
        if folder_id:
            folder_ids = {f.get("id") for f in uc.get("folders", [])}
            if folder_id not in folder_ids:
                folder_id = ""
    uc["papers"][paper_id] = {
        "added_at": time.time(),
        "folder_id": folder_id or "",
        "note": "",
    }
    _save_user_collections(uid, uc)
    # 缓存论文元数据
    if paper_meta:
        _cache_paper_meta(user_id, paper_id, paper_meta)
    return {"status": "ok", "paper_id": paper_id}


def remove_favorite(user_id: Optional[str], paper_id: str) -> Dict:
    """移除收藏。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    uc["papers"].pop(paper_id, None)
    _save_user_collections(uid, uc)
    return {"status": "ok"}


def is_favorited(user_id: Optional[str], paper_id: str) -> bool:
    """检查是否已收藏。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    return paper_id in uc.get("papers", {})


def list_favorites(
    user_id: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> Dict:
    """列出收藏夹。

    folder_id 语义：
      - None  → 不过滤，返回全部收藏
      - ""    → 仅返回未分类（folder_id 为空的论文）
      - "xxx" → 仅返回该文件夹下的论文
    """
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    papers = uc.get("papers", {})
    items = []
    for pid, info in papers.items():
        item = {"paper_id": pid, **info}
        # 按文件夹过滤
        if folder_id is not None:
            paper_fid = info.get("folder_id") or ""
            if paper_fid != folder_id:
                continue
        items.append(item)
    # 按时间倒序
    items.sort(key=lambda x: x.get("added_at", 0), reverse=True)
    return {"favorites": items, "total": len(items)}


# ------------------------------------------------------------------ #
# 文件夹
# ------------------------------------------------------------------ #

def list_folders(user_id: Optional[str] = None) -> Dict:
    """列出所有文件夹。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    folders = uc.get("folders", [])
    return {"folders": folders, "total": len(folders)}


def create_folder(
    user_id: Optional[str], name: str, description: str = ""
) -> Dict:
    """创建文件夹。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    folder = {
        "id": f"f{uuid.uuid4().hex[:8]}",
        "name": name,
        "description": description,
        "created_at": time.time(),
    }
    uc.setdefault("folders", []).append(folder)
    _save_user_collections(uid, uc)
    return {"status": "ok", "folder": folder}


def delete_folder(user_id: Optional[str], folder_id: str) -> Dict:
    """删除文件夹（不删除内部论文，改为未分类）。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    uc["folders"] = [f for f in uc.get("folders", []) if f["id"] != folder_id]
    # 把该文件夹下的论文改为未分类
    for pid, info in uc.get("papers", {}).items():
        if info.get("folder_id") == folder_id:
            info["folder_id"] = ""
    # 默认收藏文件夹被删除时同步清空
    if uc.get("default_folder_id") == folder_id:
        uc["default_folder_id"] = ""
    _save_user_collections(uid, uc)
    return {"status": "ok"}


def rename_folder(user_id: Optional[str], folder_id: str, name: str) -> Dict:
    """重命名文件夹。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    for f in uc.get("folders", []):
        if f["id"] == folder_id:
            f["name"] = name
            break
    _save_user_collections(uid, uc)
    return {"status": "ok"}


def get_default_folder(user_id: Optional[str] = None) -> Dict:
    """获取用户设置的默认收藏文件夹 id（"" 表示未设置）。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    return {"status": "ok", "folder_id": uc.get("default_folder_id", "") or ""}


def set_default_folder(user_id: Optional[str], folder_id: str) -> Dict:
    """设置默认收藏文件夹。folder_id="" 表示恢复为未分类。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    fid = (folder_id or "").strip()
    if fid:
        folder_ids = {f.get("id") for f in uc.get("folders", [])}
        if fid not in folder_ids:
            return {"status": "error", "detail": "文件夹不存在，请刷新后重试"}
    uc["default_folder_id"] = fid
    _save_user_collections(uid, uc)
    return {"status": "ok", "folder_id": fid}


def move_paper_to_folder(
    user_id: Optional[str], paper_id: str, folder_id: Optional[str]
) -> Dict:
    """移动论文到文件夹。folder_id=None 表示未分类。"""
    uid = user_id or "web-anonymous"
    uc = _get_user_collections(uid)
    if paper_id in uc.get("papers", {}):
        uc["papers"][paper_id]["folder_id"] = folder_id or ""
        _save_user_collections(uid, uc)
        return {"status": "ok"}
    # 找不到论文时明确报错，避免前端误以为移动成功
    return {"status": "error", "detail": "论文不在收藏夹中，请刷新后重试"}


# ------------------------------------------------------------------ #
# 已阅论文
# ------------------------------------------------------------------ #

def _get_read_data(user_id: Optional[str] = None) -> Dict:
    """获取已阅数据。"""
    uid = user_id or "web-anonymous"
    data = _read_json(_READ_PAPERS_FILE, {})
    if uid not in data:
        data[uid] = {}
        _write_json(_READ_PAPERS_FILE, data)
    return data[uid]


def _save_read_data(user_id: str, user_data: Dict) -> None:
    """保存已阅数据。"""
    data = _read_json(_READ_PAPERS_FILE, {})
    data[user_id] = user_data
    _write_json(_READ_PAPERS_FILE, data)


def list_read_papers(user_id: Optional[str] = None) -> Dict:
    """列出已阅论文。"""
    uid = user_id or "web-anonymous"
    rd = _get_read_data(uid)
    papers = [{"paper_id": pid, "read_at": ts} for pid, ts in rd.items()]
    papers.sort(key=lambda x: x.get("read_at", 0), reverse=True)
    return {"papers": papers, "total": len(papers)}


def add_read_paper(user_id: Optional[str], paper_id: str) -> Dict:
    """标记为已阅。"""
    uid = user_id or "web-anonymous"
    rd = _get_read_data(uid)
    rd[paper_id] = time.time()
    _save_read_data(uid, rd)
    return {"status": "ok", "paper_id": paper_id}


def remove_read_paper(user_id: Optional[str], paper_id: str) -> Dict:
    """取消已阅。"""
    uid = user_id or "web-anonymous"
    rd = _get_read_data(uid)
    rd.pop(paper_id, None)
    _save_read_data(uid, rd)
    return {"status": "ok"}


def is_read(user_id: Optional[str], paper_id: str) -> bool:
    """检查是否已阅。"""
    uid = user_id or "web-anonymous"
    rd = _get_read_data(uid)
    return paper_id in rd


# ------------------------------------------------------------------ #
# 用户认证（简单 hash，非生产级）
# ------------------------------------------------------------------ #

def _load_users() -> Dict:
    """加载用户数据。"""
    data = _read_json(_USERS_FILE, {"users": []})
    return data


def _save_users(data: Dict) -> None:
    """保存用户数据。"""
    _write_json(_USERS_FILE, data)


def _hash_password(password: str, salt: str = "") -> tuple:
    """密码 hash。返回 (hash, salt)。"""
    if not salt:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return h, salt


def register_user(username: str, password: str) -> Dict:
    """注册新用户。"""
    if not username or not password:
        return {"status": "error", "detail": "用户名和密码不能为空"}
    if len(username) < 2:
        return {"status": "error", "detail": "用户名至少 2 个字符"}
    if len(password) < 4:
        return {"status": "error", "detail": "密码至少 4 个字符"}

    data = _load_users()
    users = data.get("users", [])
    for u in users:
        if u["username"] == username:
            return {"status": "error", "detail": "用户名已存在"}

    pw_hash, salt = _hash_password(password)
    users.append({
        "username": username,
        "salt": salt,
        "password_hash": pw_hash,
        "created_at": time.time(),
    })
    data["users"] = users
    _save_users(data)

    # 初始化收藏和已阅存储
    collections = _read_json(_COLLECTIONS_FILE, {})
    collections[username] = {"papers": {}, "folders": []}
    _write_json(_COLLECTIONS_FILE, collections)

    read_data = _read_json(_READ_PAPERS_FILE, {})
    read_data[username] = {}
    _write_json(_READ_PAPERS_FILE, read_data)

    token = secrets.token_hex(32)
    return {"status": "ok", "username": username, "token": token}


def ensure_admin_user(username: str = "admin", password: str = "admin123") -> bool:
    """确保内置管理员账号存在（幂等）。返回是否新建。"""
    data = _load_users()
    users = data.get("users", [])
    if any(u.get("username") == username for u in users):
        return False
    pw_hash, salt = _hash_password(password)
    users.append({
        "username": username,
        "salt": salt,
        "password_hash": pw_hash,
        "created_at": time.time(),
        "is_admin": True,
    })
    data["users"] = users
    _save_users(data)
    # 初始化管理员自己的收藏和已阅存储
    collections = _read_json(_COLLECTIONS_FILE, {})
    collections.setdefault(username, {"papers": {}, "folders": []})
    _write_json(_COLLECTIONS_FILE, collections)
    read_data = _read_json(_READ_PAPERS_FILE, {})
    read_data.setdefault(username, {})
    _write_json(_READ_PAPERS_FILE, read_data)
    return True


def login_user(username: str, password: str) -> Dict:
    """登录。"""
    data = _load_users()
    for u in data.get("users", []):
        if u["username"] == username:
            pw_hash, _ = _hash_password(password, u.get("salt", ""))
            if pw_hash == u.get("password_hash"):
                token = secrets.token_hex(32)
                # 简单 token 存储（追加到用户数据）
                tokens = u.setdefault("tokens", {})
                tokens[token] = time.time()
                _save_users(data)
                return {"status": "ok", "username": username, "token": token}
            return {"status": "error", "detail": "密码错误"}
    return {"status": "error", "detail": "用户不存在，请先注册"}


def change_password(token: str, old_password: str, new_password: str) -> Dict:
    """修改密码：校验旧密码后更新为新密码（新 salt 重新 hash）。"""
    username = verify_token(token) if token else None
    if not username:
        return {"status": "error", "detail": "登录状态已失效，请重新登录"}
    if not old_password or not new_password:
        return {"status": "error", "detail": "请填写当前密码和新密码"}
    if len(new_password) < 4:
        return {"status": "error", "detail": "新密码至少 4 位"}
    data = _load_users()
    for u in data.get("users", []):
        if u["username"] == username:
            old_hash, _ = _hash_password(old_password, u.get("salt", ""))
            if old_hash != u.get("password_hash"):
                return {"status": "error", "detail": "当前密码不正确"}
            new_hash, new_salt = _hash_password(new_password)
            u["salt"] = new_salt
            u["password_hash"] = new_hash
            u.setdefault("tokens", {})
            # 改密码后使其他会话失效，保留当前会话
            for t in list(u["tokens"].keys()):
                if t != token:
                    del u["tokens"][t]
            _save_users(data)
            return {"status": "ok", "username": username}
    return {"status": "error", "detail": "用户不存在，请先注册"}


def logout_user(token: str) -> Dict:
    """登出。"""
    if not token:
        return {"status": "ok"}
    data = _load_users()
    for u in data.get("users", []):
        tokens = u.get("tokens", {})
        if token in tokens:
            del tokens[token]
            _save_users(data)
            return {"status": "ok"}
    return {"status": "ok"}


def verify_token(token: str) -> Optional[str]:
    """验证 token，返回用户名或 None。"""
    if not token:
        return None
    data = _load_users()
    for u in data.get("users", []):
        tokens = u.get("tokens", {})
        if token in tokens:
            return u["username"]
    return None
