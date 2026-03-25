from django.test import TestCase

from houses.crawlers import GarretCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

# HTML for first date (March 1) - two PRESENTS-only events
FIRST_DATE_HTML = """\
<html lang="ja"><head><title>GARRET OPEN!!</title></head><body>
<font size="+2">
<a href="garret_2026schedule_2.html"><img src="../../image/logo_left.jpg"></a>
<b> 2026.<strong>3 March </strong></b>
<a href="garret_2026schedule_4.html"><img src="../../image/logo_right.jpg"></a>
</font>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/01.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/7sun.jpg" width="40" height="14"><br>
<img src="../../image/garret_week/daytime_red.jpg" width="70" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p><span style="font-size: 10px"><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px">
<strong>わたあめびーすたーず PRESENTS</strong>
</span></span><br><br>
OPEN TBA | START TBA<br>
ADV TBA  | DOOR TBA  (+1D)<br>
[TICKET INFO] TBA</span></p></td>
</tr></table>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/01.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/7sun.jpg" width="40" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p><span style="font-size: 10px"><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px">
<strong>MUSIC FRONTIER PRESENTS</strong>
</span></span><br><br>
OPEN TBA | START TBA<br>
ADV TBA  | DOOR TBA  (+1D)<br>
[TICKET INFO] TBA</span></p></td>
</tr></table>
<hr>
</body></html>
"""

# HTML for last date (March 31) - "COMING SOON" plus a real event on day 29
LAST_DATE_HTML = """\
<html lang="ja"><head><title>GARRET OPEN!!</title></head><body>
<font size="+2">
<a href="garret_2026schedule_2.html"><img src="../../image/logo_left.jpg"></a>
<b> 2026.<strong>3 March </strong></b>
<a href="garret_2026schedule_4.html"><img src="../../image/logo_right.jpg"></a>
</font>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/29.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/7sun.jpg" width="40" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p>
<span style="font-size: 10px">
なせぐみ生誕2026<br><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px"><strong>
ななせぐみ / バンドじゃないもん！MAXX NAKAYOSHI<br>
グミカナミル&amp;おやすみホログラム
</strong></span></span><br><br>
OPEN 18:30 | START 19:00<br>
ADV &yen;4980  | DOOR TBA  (+1D)<br>
<a href="https://banmon.jp/contents/1048965">OFFICIAL SITE</a>
</span></p></td>
</tr></table>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/31.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/2tue.jpg" width="40" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p><span style="font-size: 10px">pre.<br><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px">
<strong>INFORMATION COMING SOON...</strong>
</span><br>and more...</span><br><br>
OPEN TBA | START TBA<br>
ADV TBA  | DOOR TBA  (+1D)<br>
[TICKET INFO] TBA</span></p></td>
</tr></table>
<hr>
</body></html>
"""

# HTML for mid-month events with multiple performers and times
MULTI_PERFORMER_HTML = """\
<html lang="ja"><head><title>GARRET OPEN!!</title></head><body>
<font size="+2"><b> 2026.<strong>3 March </strong></b></font>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/07.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/6sat.jpg" width="40" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p><span style="font-size: 10px">
Tweyelight pre.<br><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px"><strong>
Tweyelight / LADYBABY / Dimrays / BabyFaith<br>
DREAMY / The Number Zero / Phantom Excaliver<br>
DIZZYREVERSE / DisconnectCendrillon / はるちょん
</strong></span></span><br><br>
OPEN 15:50 | START 16:20<br>
ADV &yen;4900 | DOOR &yen;5400 (+1D)<br>
[TICKET INFO] <a href="https://livepocket.jp/e/1nijy">livepocket</a>
</span></p></td>
</tr></table>
<hr>
<table cellpadding="0"><tr>
<td width="80" height="90" align="center" valign="middle"><em><strong>
<img src="../../web-content/image/garret_day/27.jpg" height="40" width="40"><br>
<img src="../../image/garret_week/5fri.jpg" width="40" height="14"><br>
</strong></em></td>
<td width="700" valign="middle"><p><span style="font-size: 10px">
ストレプトカーパス<br><br>
<span style="font-size: 10px; font-weight: normal;">
<span style="font-size: 14px"><strong>
Days,near LAND / BACKDAV / 283(MouthPeace)<br>
ONE:BRAiNN / Crows of Scenery
</strong></span></span><br><br>
OPEN 17:45 | START 18:15<br>
ADV &yen;3500| DOOR &yen;4000  (+1D)<br>
[TICKET INFO] <a href="https://livepocket.jp/e/o_2m4">livepocket</a>
</span></p></td>
</tr></table>
<hr>
</body></html>
"""


class TestGarretCrawler(TestCase):
    """Test cases for Garret crawler parsing logic."""

    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="http://www.cyclone1997.com/garret/garret_schedule.html",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="GarretCrawler",
        )
        self.crawler = GarretCrawler(self.website)

    def test_extract_live_house_info(self):
        """Garret info is hardcoded."""
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "GARRET")
        self.assertEqual(info["name_kana"], "ギャレット")
        self.assertEqual(info["name_romaji"], "GARRET")

    def test_first_date_presents_only_skipped(self):
        """March 1: PRESENTS-only events have no performers, skipped."""
        schedules = self.crawler.extract_performance_schedules(FIRST_DATE_HTML)
        self.assertEqual(len(schedules), 0)

    def test_last_date_coming_soon_skipped(self):
        """March 31 'COMING SOON' skipped, day 29 parses correctly."""
        schedules = self.crawler.extract_performance_schedules(LAST_DATE_HTML)

        self.assertEqual(len(schedules), 1)

        schedule = schedules[0]
        self.assertEqual(schedule["date"], "2026-03-29")
        self.assertEqual(schedule["open_time"], "18:30")
        self.assertEqual(schedule["start_time"], "19:00")
        self.assertIn("ななせぐみ", schedule["performers"])
        self.assertIn(
            "バンドじゃないもん！MAXX NAKAYOSHI",
            schedule["performers"],
        )
        self.assertIn(
            "グミカナミル&おやすみホログラム",
            schedule["performers"],
        )

    def test_multi_performer_slash_and_br_split(self):
        """Performers separated by / and <br> all extracted."""
        schedules = self.crawler.extract_performance_schedules(
            MULTI_PERFORMER_HTML,
        )

        self.assertEqual(len(schedules), 2)

        # Day 7: Tweyelight Fest - 10 performers
        day7 = schedules[0]
        self.assertEqual(day7["date"], "2026-03-07")
        self.assertEqual(day7["open_time"], "15:50")
        self.assertEqual(day7["start_time"], "16:20")
        expected_performers = [
            "Tweyelight",
            "LADYBABY",
            "Dimrays",
            "BabyFaith",
            "DREAMY",
            "The Number Zero",
            "Phantom Excaliver",
            "DIZZYREVERSE",
            "DisconnectCendrillon",
            "はるちょん",
        ]
        self.assertEqual(day7["performers"], expected_performers)

        # Day 27: 5 performers
        day27 = schedules[1]
        self.assertEqual(day27["date"], "2026-03-27")
        self.assertEqual(day27["open_time"], "17:45")
        self.assertEqual(day27["start_time"], "18:15")
        self.assertIn("Days,near LAND", day27["performers"])
        self.assertIn("BACKDAV", day27["performers"])
        self.assertIn("283(MouthPeace)", day27["performers"])
        self.assertIn("ONE:BRAiNN", day27["performers"])
        self.assertIn("Crows of Scenery", day27["performers"])

    def test_year_month_extraction(self):
        """Year and month extracted from header text."""
        soup = self.crawler.create_soup(FIRST_DATE_HTML)
        year, month = self.crawler._extract_year_month(soup)
        self.assertEqual(year, 2026)
        self.assertEqual(month, 3)

    def test_find_next_month_link(self):
        """Next month link found from navigation arrows."""
        url = self.crawler.find_next_month_link(FIRST_DATE_HTML)
        expected = "http://www.cyclone1997.com/garret/g_schedule/garret_2026schedule_4.html"
        self.assertEqual(url, expected)

    def test_find_next_month_link_no_forward(self):
        """No next month link when only backward navigation exists."""
        html = """
        <html><body>
        <a href="garret_2026schedule_2.html"><img></a>
        <b> 2026.<strong>3 March </strong></b>
        </body></html>
        """
        url = self.crawler.find_next_month_link(html)
        self.assertIsNone(url)
