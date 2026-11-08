"""The Hebrew UI: served as right-to-left, with its logo, and the tool chips read in Hebrew."""
import json

from app.agent import _summarise_result


def test_ui_is_hebrew_right_to_left_with_a_logo(client):
    html = client.get("/").text
    assert 'lang="he"' in html and 'dir="rtl"' in html
    assert "עוזר הכספים" in html
    assert "/static/logo.svg" in html
    logo = client.get("/static/logo.svg")
    assert logo.status_code == 200 and "<svg" in logo.text


def test_no_bakery_left_in_the_ui(client):
    for path in ("/", "/static/app.js", "/static/styles.css"):
        text = client.get(path).text.lower()
        assert "bakery" not in text and "croissant" not in text and "🥐" not in text, path


def test_tool_chips_are_summarised_in_hebrew():
    def s(d):
        return _summarise_result(json.dumps(d, ensure_ascii=False))

    assert s({"created": True, "status": "logged", "flagged": True}) == "נרשמה · תקינה · מסומנת"
    assert s({"created": False, "reason": "duplicate", "status": "logged"}) == "כבר קיימת · תקינה"
    assert s({"created": True, "status": "needs_a_look"}) == "נרשמה · דורשת בדיקה"
    assert s({"matches": []}) == "לא נמצאה התאמה"
    assert s({"matches": [1, 2]}) == "2 התאמות"
    assert s({"row_count": 8, "metric": "budget", "group_by": "chapter"}) == "8 שורות"
    assert s({"metric": "utilization", "value": 87.54}) == "ניצול: 87.5%"
    assert s({"metric": "spent", "value": 1234567.4}) == "הוצאה: 1,234,567"
