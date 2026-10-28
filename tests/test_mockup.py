from PIL import Image

from leadgen import niches
from leadgen.mockup import MockupBuilder, should_build
from leadgen.mockup.palette import contrast, palette_from_logo
from leadgen.mockup.prices import parse_prices


def hex_to_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def test_palette_picks_logo_color_and_keeps_contrast(tmp_path):
    logo = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
    for x in range(20, 80):
        for y in range(20, 80):
            logo.putpixel((x, y), (230, 60, 40, 255))  # красный на прозрачном фоне
    path = tmp_path / "logo.png"
    logo.save(path)
    pal = palette_from_logo(path)
    r, g, b = hex_to_rgb(pal.primary)
    assert r > g and r > b
    assert contrast((r, g, b), (255, 255, 255)) >= 4.5


def test_palette_falls_back_without_logo():
    assert palette_from_logo(None).primary.startswith("#")


def test_parse_prices():
    text = "Наши цены:\n- Замена экрана — от 1 500 ₽\n- Замена АКБ: 900 руб.\nДиагностика - 0 р\nАдрес: ул. Ленина"
    items = parse_prices(text)
    assert [i.title for i in items] == ["Замена экрана", "Замена АКБ", "Диагностика"]
    assert items[0].price == "от 1 500 ₽"


def test_build_mockup_from_local_logo(settings, store, raw_lead, tmp_path):
    logo = tmp_path / "l.png"
    Image.new("RGB", (40, 40), (20, 120, 60)).save(logo)
    lead_id, _ = store.upsert(raw_lead(logo_url=logo.resolve().as_uri()), "repair")
    lead = store.get(lead_id)
    assert should_build(lead, "site")
    assert not should_build(lead, "bot")
    index = MockupBuilder(settings, screenshots=False).build(lead, niches.get("repair"))
    html = index.read_text(encoding="utf-8")
    assert "Замена экрана" in html and "от 1500 ₽" in html
    assert (index.parent / "logo.png").exists()
    assert "+7 (999) 123-45-67" in html


def test_mockup_escapes_untrusted_text(settings, store, raw_lead):
    lead_id, _ = store.upsert(raw_lead(name="<script>alert(1)</script>"), "repair")
    index = MockupBuilder(settings, screenshots=False).build(store.get(lead_id), niches.get("repair"))
    assert "<script>alert(1)" not in index.read_text(encoding="utf-8")
