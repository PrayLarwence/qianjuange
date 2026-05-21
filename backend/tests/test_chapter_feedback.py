"""路线 #8 MVP: 章节反馈打分 API。"""
from __future__ import annotations


def _make_world_and_chapter(client) -> tuple[str, str]:
    wid = client.post("/api/worlds", json={"name": "测试世界"}).json()["id"]
    r = client.post(
        f"/api/worlds/{wid}/chapters",
        json={"tick": 1, "title": "第一章", "note": ""},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body.get("id") or body.get("chapter", {}).get("id")
    if not cid:
        ls = client.get(f"/api/worlds/{wid}/chapters").json()["chapters"]
        cid = ls[0]["id"]
    return wid, cid


def test_upsert_create_then_update(client):
    wid, cid = _make_world_and_chapter(client)
    r = client.put(f"/api/chapters/{cid}/feedback", json={"score": 1, "comment": "好评"})
    assert r.status_code == 200, r.text
    fb1 = r.json()
    assert fb1["chapter_id"] == cid
    assert fb1["score"] == 1
    assert fb1["comment"] == "好评"

    r = client.put(f"/api/chapters/{cid}/feedback", json={"score": -1, "comment": "改差评"})
    assert r.status_code == 200
    fb2 = r.json()
    assert fb2["id"] == fb1["id"]  # 同一行被覆盖
    assert fb2["score"] == -1
    assert fb2["comment"] == "改差评"


def test_upsert_invalid_score(client):
    _, cid = _make_world_and_chapter(client)
    r = client.put(f"/api/chapters/{cid}/feedback", json={"score": 5})
    assert r.status_code == 400
    assert "-1" in r.json()["detail"]


def test_upsert_chapter_not_found(client):
    r = client.put("/api/chapters/c_does_not_exist/feedback", json={"score": 1})
    assert r.status_code == 404


def test_delete_feedback(client):
    _, cid = _make_world_and_chapter(client)
    client.put(f"/api/chapters/{cid}/feedback", json={"score": 1})
    r = client.delete(f"/api/chapters/{cid}/feedback")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    # 再删一次返回 0 不报错
    r = client.delete(f"/api/chapters/{cid}/feedback")
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


def test_list_feedback_aggregates_summary(client):
    wid = client.post("/api/worlds", json={"name": "聚合世界"}).json()["id"]
    chap_ids = []
    for tick in (1, 2, 3, 4):
        client.post(
            f"/api/worlds/{wid}/chapters",
            json={"tick": tick, "title": f"第 {tick} 章"},
        )
    chap_ids = [c["id"] for c in client.get(f"/api/worlds/{wid}/chapters").json()["chapters"]]
    assert len(chap_ids) == 4

    client.put(f"/api/chapters/{chap_ids[0]}/feedback", json={"score": 1})
    client.put(f"/api/chapters/{chap_ids[1]}/feedback", json={"score": 1})
    client.put(f"/api/chapters/{chap_ids[2]}/feedback", json={"score": -1, "comment": "差"})
    # chap_ids[3] 不打分

    r = client.get(f"/api/worlds/{wid}/chapter_feedback")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == {
        "total_chapters": 4,
        "rated": 3,
        "good": 2,
        "neutral": 0,
        "bad": 1,
    }
    assert len(body["items"]) == 4
    by_chapter = {it["chapter_id"]: it for it in body["items"]}
    assert by_chapter[chap_ids[0]]["feedback"]["score"] == 1
    assert by_chapter[chap_ids[2]]["feedback"]["comment"] == "差"
    assert by_chapter[chap_ids[3]]["feedback"] is None  # 未打分


def test_list_feedback_world_not_found(client):
    r = client.get("/api/worlds/w_nope/chapter_feedback")
    assert r.status_code == 404


def test_comment_truncated_to_2000(client):
    _, cid = _make_world_and_chapter(client)
    long = "啊" * 3000
    r = client.put(f"/api/chapters/{cid}/feedback", json={"score": 0, "comment": long})
    assert r.status_code == 200
    assert len(r.json()["comment"]) == 2000


def test_delete_world_does_not_orphan_feedback(client):
    """删除 chapter 后, 反馈虽然按 schema 还在表里(无 ON DELETE CASCADE),
    但 list 接口只列存在的 chapter 反馈, 因此不会暴露给前端。"""
    wid, cid = _make_world_and_chapter(client)
    client.put(f"/api/chapters/{cid}/feedback", json={"score": 1})
    # 删 chapter
    r = client.delete(f"/api/chapters/{cid}")
    assert r.status_code == 200
    # list 不应该再列出
    body = client.get(f"/api/worlds/{wid}/chapter_feedback").json()
    assert body["summary"]["rated"] == 0
    assert body["items"] == []
