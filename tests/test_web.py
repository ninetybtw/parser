from fastapi.testclient import TestClient

from leadgen.db import Store
from leadgen.web.app import create_app, safe_url


def test_safe_url():
    assert safe_url("https://vk.com/x") == "https://vk.com/x"
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url(None) == ""


def test_card_flow(settings, raw_lead):
    s = Store(settings.db_path)
    lead_id, _ = s.upsert(raw_lead(contact_url="javascript:alert(1)"), "repair")
    s.set_offer(lead_id, "Тема", "Черновик текста", "site", "template")
    s.close()

    client = TestClient(create_app(settings))
    assert "Ремонт телефонов Мастер" in client.get("/").text
    page = client.get(f"/leads/{lead_id}").text
    assert "Черновик текста" in page
    assert "javascript:alert" not in page

    r = client.post(f"/leads/{lead_id}/offer", data={"subject": "Т", "text": "Правка"}, follow_redirects=False)
    assert r.status_code == 303
    client.post(f"/leads/{lead_id}/status", data={"status": "sent"})
    page = client.get(f"/leads/{lead_id}").text
    assert "Правка" in page and "отправлено сегодня: 1" in page

    assert client.post(f"/leads/{lead_id}/status", data={"status": "bogus"}).status_code == 400


def test_cross_origin_post_rejected(settings):
    client = TestClient(create_app(settings))
    r = client.post("/leads/1/status", data={"status": "sent"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_data_dir_is_not_served(settings):
    client = TestClient(create_app(settings))
    assert client.get("/mockups/../leads.sqlite3").status_code == 404
