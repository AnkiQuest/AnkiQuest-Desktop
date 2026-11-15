# Streak picture checks

Generated with the real Qt renderer on Anki 26.9.4, using Segoe UI and
Microsoft YaHei for the checked captures. The companion pixels come from
the bundled exports; no art was changed. Reviewed all five PNGs for legible
text, complete art, spacing and clipping.

| Days | Capture |
| --- | --- |
| 1 | [Warm](streak-1.png) |
| 7 | [Hot](streak-7.png) |
| 30 | [Blazing](streak-30.png) |
| 100 | [Legend](streak-100.png) |
| 10,000 | [German, twice the text size](streak-large-localized.png) |

`tests/qt_share.py` checks both ends of every heat boundary from
`tests/fixtures/streak_moods.json`, the next milestone, the gold number,
localized grouping, width limits and the core-art fallback. The native
picker test checks that online previews and exports use this design too,
without publishing a link. `tests/qt_moments.py` checks the daily moment's
count reaches the renderer.

To regenerate, set `ANKIQUEST_QT_CAPTURE` to this directory, then run the
`LocalPicture.test_streak_picture_capture` and
`LocalPicture.test_streak_number_is_gold_localized_and_fits_large_text`
tests from `tests/qt_share.py`. Set `ANKIQUEST_QT_FONT` and optional
`ANKIQUEST_QT_FALLBACKS` to installed fonts for headless Windows captures.
