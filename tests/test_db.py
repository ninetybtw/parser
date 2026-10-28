from leadgen.models import Contacts


def test_new_lead_is_created(store, raw_lead):
    lead_id, created = store.upsert(raw_lead(), "repair", query="ремонт")
    assert created
    lead = store.get(lead_id)
    assert lead.name == "Ремонт телефонов Мастер"
    assert lead.sources[0]["query"] == "ремонт"
    assert lead.status == "new"


def test_same_source_id_is_deduplicated(store, raw_lead):
    a, _ = store.upsert(raw_lead(), "repair")
    b, created = store.upsert(raw_lead(), "repair")
    assert a == b and not created


def test_cross_source_merge_by_phone(store, raw_lead):
    a, _ = store.upsert(raw_lead(), "repair")
    tg = raw_lead(source="telegram", external_id="555", url="https://t.me/master",
                  contacts=Contacts(phones=["79991234567"], telegram=["master"]), description="")
    b, created = store.upsert(tg, "repair")
    assert a == b and not created
    lead = store.get(a)
    assert lead.contacts.telegram == ["master"]
    assert {s["source"] for s in lead.sources} == {"vk", "telegram"}
    # Описание не затирается более коротким
    assert "Замена экрана" in lead.description


def test_shared_hosts_do_not_merge_different_businesses(store, raw_lead):
    a, _ = store.upsert(raw_lead(contacts=Contacts(websites=["https://taplink.cc/salon_a"])), "beauty")
    b, created = store.upsert(
        raw_lead(external_id="2", contacts=Contacts(websites=["https://taplink.cc/salon_b"])), "beauty"
    )
    assert created and a != b


def test_same_domain_merges(store, raw_lead):
    a, _ = store.upsert(raw_lead(contacts=Contacts(websites=["https://www.fix.ru"])), "repair")
    b, created = store.upsert(raw_lead(source="rss:x", external_id="z", contacts=Contacts(websites=["fix.ru/price"])), "repair")
    assert a == b and not created


def test_do_not_contact_blocks_future_results(store, raw_lead):
    lead_id, _ = store.upsert(raw_lead(), "repair")
    store.set_status(lead_id, "do_not_contact")
    other_source = raw_lead(source="telegram", external_id="9", contacts=Contacts(phones=["79991234567"]))
    assert store.is_blocked(other_source)
    assert store.is_blocked(raw_lead())
    assert not store.is_blocked(raw_lead(external_id="77", contacts=Contacts()))


def test_offer_moves_new_to_ready_and_sent_is_counted(store, raw_lead):
    lead_id, _ = store.upsert(raw_lead(), "repair")
    store.set_offer(lead_id, "Тема", "Текст", "site", "template")
    assert store.get(lead_id).status == "ready"
    store.set_status(lead_id, "sent")
    assert store.sent_today() == 1
    assert store.ids_without_offer() == []
