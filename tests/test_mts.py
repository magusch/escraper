import pytest
import requests
from datetime import datetime
from pathlib import Path

from escraper.parsers import MTS

from .testing import Response


TESTDATA = Path(__file__).parent / "test_data" / "test_mts"
ZEROS = dict(second=00, microsecond=00)


def get_mts_date():
    return datetime.now(tz=MTS.TIMEZONE).strftime(MTS.DATETIME_STRF)


#######################################
## mts get_event
#######################################
def test_mts_get_event_with_none():
    with pytest.raises(ValueError):
        MTS().get_event()

@pytest.fixture
def requests_get_event(monkeypatch):
    def get(path, **kwargs):
        with open(path + ".html") as file:
            text = file.read()

        return Response(ok=True, text=text)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA) + "/")
    #monkeypatch.setattr(MTS, "BASE_EVENTS_API", str(TESTDATA) + "/")


def test_mts_get_event(requests_get_event):
    event_url = MTS().BASE_URL+'event_card_1'
    event = MTS().get_event(event_url=event_url)

    #event = events[0]

    assert event.adress == "Невский проспект, дом 35 (улица Садовая, дом 17)"
    assert event.category == "Концерты"
    assert event.date_from == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30, **ZEROS)
    assert event.date_to == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30, **ZEROS)
    #assert event.date_from_to == "01 января, 00:00"
    assert event.id == MTS.parser_prefix + event_url.split('eventId=')[-1].split('&')[0].split('#')[0]
    assert event.place_name == "Двор Гостинки"
    assert event.full_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.post_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.poster_imag == "https://live.mts.ru/image/full/063ca253-4ff1-6e01-c8a7-4604b102467c.jpg"
    assert event.price == "1500₽"
    assert event.title[2:] == "Концерт группы «Хлеб». Summer Sound x билайн"  # without emoji
    assert event.is_registration_open is True


def test_mts_get_event_2(requests_get_event):
    event_url = MTS().BASE_URL+'event_card_2'
    event = MTS().get_event(event_url=event_url)

    #event = events[0]

    assert event.adress == "Невский проспект, дом 35 (улица Садовая, дом 17)"
    assert event.category == "Концерты"
    assert event.date_from == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30, **ZEROS)
    assert event.date_to == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30, **ZEROS)
    #assert event.date_from_to == "01 января, 00:00"
    assert event.id == MTS.parser_prefix + event_url.split('eventId=')[-1].split('&')[0].split('#')[0]
    assert event.place_name == "Двор Гостинки"
    assert event.full_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.post_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.poster_imag == "https://live.mts.ru/image/full/063ca253-4ff1-6e01-c8a7-4604b102467c.jpg"
    assert event.price == "на сайте"
    assert event.title[2:] == "Концерт группы «Хлеб». Summer Sound x билайн"  # without emoji
    assert event.is_registration_open is True

#######################################
## mts get_events
#######################################
@pytest.fixture
def requests_get_events(monkeypatch):
    def get(path, **kwargs):
        with open(path + ".html") as file:
            text = file.read()

        return Response(ok=True, text=text)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA) )



def test_mts_get_events(requests_get_events):
    params = {"date_from": '2024-05-20', "date_to": '2024-05-20', "city":'test_city', "categories":['ribbon']}
    events = MTS().get_events(request_params=params)

    assert len(events) == 3

    event = events[0]

    assert event.adress == "Невский проспект, дом 35 (улица Садовая, дом 17)"
    assert event.category == "Концерты"
    assert event.date_from == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30,
                                                                    **ZEROS)
    assert event.date_to == datetime.now(tz=MTS.TIMEZONE).replace(year=2024, month=8, day=9, hour=19, minute=30,
                                                                  **ZEROS)
    assert event.id == MTS.parser_prefix + '111'
    assert event.place_name == "Двор Гостинки"
    assert event.full_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.post_text == "Эти ребята регулярно собирают миллионы просмотров на YouTube. \nПотому что умеют превращать музыку в комедийную сатиру"
    assert event.poster_imag == "https://live.mts.ru/image/full/063ca253-4ff1-6e01-c8a7-4604b102467c.jpg"
    assert event.price == "1500₽"
    assert event.title[2:] == "Концерт группы «Хлеб». Summer Sound x билайн"  # without emoji
    assert event.is_registration_open is True


# @pytest.fixture
# def requests_get_empty(monkeypatch):
#     def get(*args, **kwargs):
#         return Response(ok=False)
#
#     monkeypatch.setattr(requests, "get", get)
#
#
#
# def test_mts_get_events_incorrect_category():
#     params = {
#         "from": get_mts_date(),
#         "to": get_mts_date(),
#         "category": ["Invalid_category"],
#     }
#     with pytest.warns(UserWarning, match="Category 'Invalid_category' is not exist"):
#         events = MTS().get_events(request_params=params)


# def test_mts_get_events_date_for_request(requests_get_events):
#     with pytest.warns(UserWarning):
#         MTS().get_events(request_params={"city": "not_existed"})
#
#
# #######################################
# ## mts _adress
# #######################################
# @pytest.fixture
# def requests_get_adress_online(monkeypatch):
#     def get(path, **kwargs):
#         with open(path + ".html") as file:
#             text = file.read()
#
#         return Response(ok=True, text=text)
#
#     monkeypatch.setattr(requests, "get", get)
#     monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA / "event_card_2"))
#     monkeypatch.setattr(MTS, "BASE_EVENTS_API", str(TESTDATA) + "/")
#
#
# def test_mts_adress_online(requests_get_adress_online):
#     events = MTS().get_events(tags=["adress"])
#
#     assert len(events) == 1
#
#     event = events[0]
#     assert event.adress == "Онлайн"
#
#
# @pytest.fixture
# def requests_get_adress_saint_petersburg(monkeypatch):
#     def get(path, **kwargs):
#         with open(path + ".html") as file:
#             text = file.read()
#
#         return Response(ok=True, text=text)
#
#     monkeypatch.setattr(requests, "get", get)
#     monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA / "event_card_3"))
#     monkeypatch.setattr(MTS, "BASE_EVENTS_API", str(TESTDATA) + "/")
#
#
# def test_mts_adress_saint_petersburg(requests_get_adress_saint_petersburg):
#     events = MTS().get_events(tags=["adress"])
#
#     assert len(events) == 1
#
#     event = events[0]
#     assert event.adress == "Test avenue"
#
#
# @pytest.fixture
# def requests_get_address_without_cityname(monkeypatch):
#     def get(path, **kwargs):
#         with open(path + ".html") as file:
#             text = file.read()
#
#         return Response(ok=True, text=text)
#
#     monkeypatch.setattr(requests, "get", get)
#     monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA / "event_card_4"))
#     monkeypatch.setattr(MTS, "BASE_EVENTS_API", str(TESTDATA) + "/")
#
#
# def test_mts_address_without_cityname(requests_get_adress_without_cityname):
#     events = MTS().get_events(tags=["adress"])
#
#     assert len(events) == 1
#
#     event = events[0]
#     assert event.adress == "Test avenue, 111"
#
#
# @pytest.mark.parametrize(
#     "test_file, date_from, date_to",
#     [
#         ("event_card_5", datetime.now(tz=MTS.TIMEZONE).replace(month=1, day=1, hour=00, **ZEROS), datetime.now(tz=MTS.TIMEZONE).replace(month=1, day=1, hour=1, **ZEROS)),
#         ("event_card_6", datetime.now(tz=MTS.TIMEZONE).replace(month=1, day=1, hour=00, **ZEROS), None),
#         ("event_card_7", datetime.now(tz=MTS.TIMEZONE).replace(month=1, day=1, hour=00, **ZEROS), datetime.now(tz=MTS.TIMEZONE).replace(month=1, day=2, hour=00, **ZEROS)),
#     ],
#     ids=[
#         "dd month, HH:MM-HH:MM",
#         "dd month, HH:MM",
#         "dd-dd month",
#     ],
# )
# def test_mts_date_from_to(monkeypatch, test_file, date_from, date_to):
#     def get(path, **kwargs):
#         with open(path + ".html") as file:
#             text = file.read()
#
#         return Response(ok=True, text=text)
#
#     monkeypatch.setattr(requests, "get", get)
#     monkeypatch.setattr(MTS, "BASE_URL", str(TESTDATA / test_file))
#     monkeypatch.setattr(MTS, "BASE_EVENTS_API", str(TESTDATA) + "/")
#
#     events = MTS().get_events(tags=["date_from", "date_to"])
#
#     assert len(events) == 1
#
#     event = events[0]
#     assert event.date_from == date_from and event.date_to == date_to
