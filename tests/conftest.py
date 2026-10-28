import pytest

from leadgen.config import Settings
from leadgen.db import Store
from leadgen.models import Contacts, PriceItem, RawLead


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path / "data", me_name="Алекс", me_contact="@alex_dev")
    s.ensure_dirs()
    return s


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def raw_lead():
    def make(**kw):
        data = dict(
            source="vk", external_id="1", url="https://vk.com/remont1", name="Ремонт телефонов Мастер",
            description="Ремонт смартфонов и ноутбуков. Замена экрана — от 1500 ₽",
            contacts=Contacts(phones=["79991234567"]),
            prices=[PriceItem(title="Замена экрана", price="от 1500 ₽")],
        )
        data.update(kw)
        return RawLead(**data)

    return make
