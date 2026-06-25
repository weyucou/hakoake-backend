from django.test import TestCase

from houses.crawlers import CycloneCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

# Minimal June 2026 schedule HTML with two events
SCHEDULE_HTML = """\
<html lang="ja"><head><meta charset="Shift_JIS"></head><body>
<font size="+2">
<a href="2026schedule_5.html"><img src="../image/logo_left_b.jpg"></a>
<b> 2026.<strong>6 June </strong></b>
<a href="2026schedule_7.html"><img src="../image/logo_right_b.jpg"></a>
</font>
<hr>
<table cellpadding="0">
  <tr>
    <td width="80" height="90" align="center" valign="middle"><em><strong>
      <img src="../image/cyclone_day/01.jpg" alt="" height="40" width="40"><br>
      <img src="../image/cyclone_week/1mon.jpg" alt="" height="14" width="40"><br>
    </strong></em></td>
    <td width="700" valign="middle"><p><span style="font-size: 10px">SHIBUYA CYCLONE pre.<br>
      <br>
      <span style="font-size: 10px; font-weight: normal;"><span style="font-size: 14px"><strong>
        BandA / BandB / BandC
      </strong></span></span><br>
      OPEN 18:00| START 18:30<br>
    </span></p></td>
  </tr>
</table>
<hr>
<table cellpadding="0">
  <tr>
    <td width="80" height="90" align="center" valign="middle"><em><strong>
      <img src="../image/cyclone_day/29.jpg" alt="" height="40" width="40"><br>
    </strong></em></td>
    <td width="700" valign="middle"><p><span style="font-size: 10px">
      <span style="font-size: 10px; font-weight: normal;"><span style="font-size: 14px"><strong>
        ナカノバンド / ヤマグチバンド
      </strong></span></span><br>
      OPEN 17:30 | START 18:00<br>
    </span></p></td>
  </tr>
</table>
<hr>
</body></html>
"""

# HTML with no next-month link
NO_NEXT_MONTH_HTML = """\
<html lang="ja"><body>
<font size="+2">
<a href="2026schedule_5.html"><img></a>
<b> 2026.<strong>6 June </strong></b>
</font>
</body></html>
"""


class TestCycloneCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="http://www.cyclone1997.com/schedule/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="CycloneCrawler",
        )
        self.crawler = CycloneCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "CYCLONE")
        self.assertEqual(info["name_romaji"], "CYCLONE")

    def test_find_schedule_link_single_digit_month(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.cyclone.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 6, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "http://www.cyclone1997.com/schedule/2026schedule_6.html")

    def test_find_schedule_link_double_digit_month(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.cyclone.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 11, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "http://www.cyclone1997.com/schedule/2026schedule_11.html")

    def test_extract_schedules_parses_dates_and_performers(self):
        schedules = self.crawler.extract_performance_schedules(SCHEDULE_HTML)
        self.assertEqual(len(schedules), 2)

        june1 = schedules[0]
        self.assertEqual(june1["date"], "2026-06-01")
        self.assertEqual(june1["open_time"], "18:00")
        self.assertEqual(june1["start_time"], "18:30")
        self.assertIn("BandA", june1["performers"])
        self.assertIn("BandB", june1["performers"])
        self.assertIn("BandC", june1["performers"])

        june29 = schedules[1]
        self.assertEqual(june29["date"], "2026-06-29")
        self.assertEqual(june29["open_time"], "17:30")
        self.assertEqual(june29["start_time"], "18:00")
        self.assertIn("ナカノバンド", june29["performers"])
        self.assertIn("ヤマグチバンド", june29["performers"])

    def test_find_next_month_link(self):
        url = self.crawler.find_next_month_link(SCHEDULE_HTML)
        self.assertEqual(url, "http://www.cyclone1997.com/schedule/2026schedule_7.html")

    def test_find_next_month_link_none_when_no_forward_link(self):
        url = self.crawler.find_next_month_link(NO_NEXT_MONTH_HTML)
        self.assertIsNone(url)

    def test_cyclone_day_images_used_not_garret(self):
        """Day extraction uses cyclone_day/ image path, not garret_day/."""
        soup = self.crawler.create_soup(SCHEDULE_HTML)
        first_table = soup.find("table")
        left_td = first_table.find("td")
        day = self.crawler._extract_day_from_images(left_td)
        self.assertEqual(day, 1)
