"""收藏夹 / 文件夹 / 默认收藏文件夹 / 导入隔离 的 Web 层回归测试。"""

from __future__ import annotations

import agent.collections as C


def _use_tmp_data(monkeypatch, tmp_path):
    """把 collections 模块的数据文件重定向到临时目录，避免污染真实数据。"""
    monkeypatch.setattr(C, "_COLLECTIONS_FILE", tmp_path / "collections.json")
    monkeypatch.setattr(C, "_READ_PAPERS_FILE", tmp_path / "read_papers.json")
    monkeypatch.setattr(C, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(C, "_PAPER_CACHE_FILE", tmp_path / "paper_cache.json")


def test_default_folder_flow(monkeypatch, tmp_path):
    """默认收藏文件夹：设置后新收藏自动落位；文件夹删除后回退未分类。"""
    _use_tmp_data(monkeypatch, tmp_path)
    f = C.create_folder(None, "tabpfn")
    fid = f["folder"]["id"]

    assert C.get_default_folder(None)["folder_id"] == ""
    assert C.set_default_folder(None, fid)["status"] == "ok"

    # 未显式指定 folder_id 时，新收藏进入默认文件夹
    C.add_favorite(None, "2301.00001", paper_meta={"title": "T", "arxiv_id": "2301.00001"})
    favs = C.list_favorites(None)["favorites"]
    assert favs[0]["folder_id"] == fid

    # 显式指定 folder_id="" 仍可强制未分类
    C.add_favorite(None, "2301.00002", paper_meta={"title": "T2", "arxiv_id": "2301.00002"},
                   folder_id="")
    assert C.list_favorites(None, folder_id="")["favorites"][0]["paper_id"] == "2301.00002"

    # 删除默认文件夹 → 默认设置清空，新收藏回退未分类
    C.delete_folder(None, fid)
    assert C.get_default_folder(None)["folder_id"] == ""
    C.add_favorite(None, "2301.00003", paper_meta={"title": "T3", "arxiv_id": "2301.00003"})
    assert C.list_favorites(None)["favorites"][0]["folder_id"] == ""


def test_set_default_folder_invalid(monkeypatch, tmp_path):
    _use_tmp_data(monkeypatch, tmp_path)
    assert C.set_default_folder(None, "not-exist")["status"] == "error"


def test_move_missing_paper_errors(monkeypatch, tmp_path):
    """移动不存在的论文必须明确报错，不能静默成功。"""
    _use_tmp_data(monkeypatch, tmp_path)
    f = C.create_folder(None, "F")
    r = C.move_paper_to_folder(None, "10.1234/abc", f["folder"]["id"])
    assert r["status"] == "error"


def test_import_user_isolation(monkeypatch, tmp_path):
    """导入接口带 user_id 时写入对应用户，不能落进匿名账号。"""
    _use_tmp_data(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    import web.app

    C.register_user("alice", "pass1234")
    client = TestClient(web.app.app)
    r = client.post("/api/favorites/import", json={
        "items": [{"id": "10.1000/xyz", "title": "P", "doi": "10.1000/xyz"}],
        "source": "bibtex",
        "user_id": "alice",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert client.get("/api/favorites?user_id=alice").json()["total"] == 1
    assert client.get("/api/favorites?user_id=web-anonymous").json()["total"] == 0


def test_auth_login_flow(monkeypatch, tmp_path):
    """注册 → 登录 → 校验 token 全链路。"""
    _use_tmp_data(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    import web.app

    client = TestClient(web.app.app)
    assert client.post("/api/auth/register",
                       json={"username": "bob", "password": "pass1234"}).json()["status"] == "ok"
    r = client.post("/api/auth/login",
                    json={"username": "bob", "password": "pass1234"})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get(f"/api/auth/me?token={token}").json()
    assert me == {"logged_in": True, "username": "bob"}
    # 错误密码必须 401
    assert client.post("/api/auth/login",
                       json={"username": "bob", "password": "wrong"}).status_code == 401


def test_homepage_and_admin_docs(monkeypatch, tmp_path):
    """首页恢复为项目介绍页；内置 admin 账号可编辑文档，普通用户不行。"""
    _use_tmp_data(monkeypatch, tmp_path)
    import web.app
    monkeypatch.setattr(web.app, "_DOCS_FILE", tmp_path / "docs_content.json")
    from fastapi.testclient import TestClient

    with TestClient(web.app.app, follow_redirects=False) as client:
        # 根路径返回介绍首页（不再 302 到 /app）
        r = client.get("/")
        assert r.status_code == 200
        assert "研索" in r.text

        # 未登录 / 普通用户不能编辑文档
        assert client.put("/api/docs", json={"sections": [{"title": "T", "body": "B"}]}).status_code == 403
        client.post("/api/auth/register", json={"username": "bob", "password": "pass1234"})
        bob_token = client.post("/api/auth/login",
                                json={"username": "bob", "password": "pass1234"}).json()["token"]
        assert client.put(f"/api/docs?token={bob_token}",
                          json={"sections": [{"title": "T", "body": "B"}]}).status_code == 403

        # 启动时已预置 admin 账号（默认 admin/admin123），可直接登录编辑并持久化
        token = client.post("/api/auth/login",
                            json={"username": "admin", "password": "admin123"}).json()["token"]
        r = client.put(f"/api/docs?token={token}",
                       json={"sections": [{"title": "配置", "body": "- A\n- B"}]})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        got = client.get(f"/api/docs?token={token}").json()
        assert got["sections"][0]["title"] == "配置"
        assert got["can_edit"] is True


def test_change_password_flow(monkeypatch, tmp_path):
    """修改密码：旧密码校验、新密码规则、改后旧密码失效。"""
    _use_tmp_data(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    import web.app

    with TestClient(web.app.app) as client:
        client.post("/api/auth/register", json={"username": "carol", "password": "pass1234"})
        token = client.post("/api/auth/login",
                            json={"username": "carol", "password": "pass1234"}).json()["token"]
        # 旧密码错误 → 400
        r = client.post("/api/auth/change-password", json={
            "token": token, "old_password": "wrong", "new_password": "newpass123"})
        assert r.status_code == 400
        # 新密码太短 → 400
        r = client.post("/api/auth/change-password", json={
            "token": token, "old_password": "pass1234", "new_password": "123"})
        assert r.status_code == 400
        # 正常修改 → 200
        r = client.post("/api/auth/change-password", json={
            "token": token, "old_password": "pass1234", "new_password": "newpass123"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # 旧密码不能再登录，新密码可以
        assert client.post("/api/auth/login",
                           json={"username": "carol", "password": "pass1234"}).status_code == 401
        assert client.post("/api/auth/login",
                           json={"username": "carol", "password": "newpass123"}).status_code == 200


def test_api_settings_flow(monkeypatch, tmp_path):
    """API Key 设置：需登录、key 脱敏、空值清除。"""
    _use_tmp_data(monkeypatch, tmp_path)
    import agent.api_settings as AS
    monkeypatch.setattr(AS, "_CONFIG_FILE", tmp_path / "api_config.json")
    from fastapi.testclient import TestClient
    import web.app

    with TestClient(web.app.app) as client:
        # 未登录保存 → 401
        assert client.put("/api/settings/api",
                          json={"openalex_key": "sk-x"}).status_code == 401
        token = client.post("/api/auth/login",
                            json={"username": "admin", "password": "admin123"}).json()["token"]
        # 保存
        r = client.put(f"/api/settings/api?token={token}", json={
            "openalex_key": "sk-secret123", "openalex_email": "a@b.c", "s2_key": "s2-secret9"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # 读取时 key 脱敏，邮箱明文
        got = client.get(f"/api/settings/api?token={token}").json()
        assert got["openalex_key"] == "sk****23"
        assert "secret" not in got["openalex_key"]
        assert got["openalex_email"] == "a@b.c"
        # 空字符串清除对应 key
        r = client.put(f"/api/settings/api?token={token}",
                       json={"openalex_key": "", "s2_key": ""})
        assert r.json()["status"] == "ok"
        got2 = client.get(f"/api/settings/api?token={token}").json()
        assert got2["openalex_key"] == ""
        assert got2["s2_key"] == ""
