from leadgen.extract import extract_contacts, host_of, normalize_phone


def test_normalize_phone_variants():
    assert normalize_phone("+7 (999) 123-45-67") == "79991234567"
    assert normalize_phone("8 999 123 45 67") == "79991234567"
    assert normalize_phone("9991234567") == "79991234567"
    assert normalize_phone("123") is None


def test_extract_contacts_from_description():
    text = (
        "Ремонт техники. Тел: 8 (912) 345-67-89, почта info@fix-it.ru\n"
        "Сайт: www.fix-it.ru, запись в tg @fixit_master или t.me/fixit_channel, vk.com/fixit"
    )
    c = extract_contacts(text)
    assert c.phones == ["79123456789"]
    assert c.emails == ["info@fix-it.ru"]
    assert "fixit_master" in c.telegram and "fixit_channel" in c.telegram
    assert c.vk == ["fixit"]
    assert c.websites == ["https://www.fix-it.ru"]


def test_email_is_not_a_telegram_handle():
    c = extract_contacts("пишите на hello@studio.ru")
    assert c.telegram == []
    assert c.emails == ["hello@studio.ru"]


def test_host_of_strips_www():
    assert host_of("https://www.Example.ru/price/") == "example.ru"
