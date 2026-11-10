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


def test_invoices_button_is_in_the_top_bar_and_attach_buttons_are_labelled(client):
    html = client.get("/").text
    top = html[html.index('<header class="topbar">'):html.index("</header>")]
    assert 'id="toggle-invoices"' in top and "חשבוניות" in top  # prominent, not buried in the sidebar foot
    assert 'id="photo"' in html and 'capture="environment"' in html  # camera capture on phones
    assert "צילום" in html and "צירוף קובץ" in html
    assert "required" not in html[html.index('<textarea id="input"'):html.index("</textarea>")]  # a photo alone can be sent


def test_chat_follows_the_stream_to_the_bottom(client):
    js = client.get("/static/app.js").text
    assert "function followAnswer" in js and "requestAnimationFrame(scrollDown)" in js
    assert "state.follow = true" in js  # every send starts following again


def test_attached_photo_is_visible_and_sending_waits_for_it(client):
    html = client.get("/").text
    # the chip with thumbnail, name and a remove button sits above the composer, where it cannot be missed
    assert html.index('id="attachment"') < html.index('id="composer"')
    assert 'id="attachment-thumb"' in html and 'id="attachment-remove"' in html
    js = client.get("/static/app.js").text
    assert "state.pending" in js and "await state.pending" in js  # a message is never sent before its photo is ready
    assert "מכין את התמונה" in js
    css = client.get("/static/styles.css").text
    assert "gap: 18px" in css  # the camera and file buttons are no longer touching on a phone
