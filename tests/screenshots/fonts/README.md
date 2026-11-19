# Screenshot fonts

`tests/qt_screenshots.py` points fontconfig at this folder only, so the screenshots use these fonts and nothing installed on the machine. The banner tool draws its title with the same Roboto.

| File | Font | Source | License |
| --- | --- | --- | --- |
| `Nunito-Regular.ttf`, `-SemiBold`, `-Bold`, `-ExtraBold` | Nunito 3.602, the Today panel's first font | `ofl/nunito/Nunito[wght].ttf` in google/fonts at `5bd87dfc525c8a0d1d8529d3684716e00c3fc59a` | `LICENSE-Nunito.txt` (OFL 1.1) |
| `Roboto-Regular.ttf`, `Roboto-Bold.ttf` | Roboto 2.138, Qt's window font | copied from `assets/fonts` | `LICENSE-Roboto.txt` (Apache 2.0) |
| `DejaVuSans-Symbols.ttf` | DejaVu Sans 2.37: arrows, box drawing, shapes, check mark | `dejavu-fonts-ttf-2.37.tar.bz2` from the dejavu-fonts release `version_2_37` | `LICENSE-DejaVu.txt` |
| `NotoColorEmoji-AnkiQuest.ttf` | Noto Color Emoji 2.057: the emoji the add-on shows | `2D/fonts/NotoColorEmoji.ttf` in googlefonts/noto-emoji at `99701e07d3d1fe1bdbcdb14964547f0fd592966f` | `LICENSE-NotoColorEmoji.txt` (OFL 1.1) |

Chromium does not pick weights from a variable font through fontconfig, so Nunito is cut into one static file per weight the add-on's CSS uses. The symbol and emoji fonts are cut to the characters the add-on shows. With fontTools 4.60.1:

```sh
for w in 400:Regular 600:SemiBold 700:Bold 800:ExtraBold; do
  SOURCE_DATE_EPOCH=0 fonttools varLib.instancer 'Nunito[wght].ttf' wght=${w%%:*} --static \
    --update-name-table -q -o Nunito-${w##*:}.ttf
done
pyftsubset DejaVuSans.ttf --unicodes='U+2190-21FF,U+2500-257F,U+25A0-25FF,U+2713' \
  --output-file=DejaVuSans-Symbols.ttf
pyftsubset NotoColorEmoji.ttf --output-file=NotoColorEmoji-AnkiQuest.ttf \
  --unicodes='U+1F389,U+1F3C6,U+1F451,U+1F4E3,U+1F4EC,U+1F525,U+1F948,U+1F949,U+23F1,U+26A1,U+2705,U+FE0F'
```

These commands give the same bytes on every run. An emoji or symbol added to the add-on needs its code point added here; until then it draws as an empty box.
