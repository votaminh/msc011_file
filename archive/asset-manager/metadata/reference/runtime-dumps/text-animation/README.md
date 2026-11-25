# CapCut text-animation runtime dump

Captured from CapCut 20.0.0 on `emulator-5556` through root Frida.

## Runtime totals

| Category | Items |
|---|---:|
| In | 149 |
| Out | 193 |
| Loop | 198 |
| Add to Favorites | 0 |
| **Category-entry total** | **540** |

There are 540 unique `effect_id` values and 531 unique display names.

## Source classification

- **Remote catalog:** all 540 entries have CDN URLs in `fileUrl`.
- Each item contains a server-populated `request_id` and fields such as
  `category_id_ex`, `category_name_ex`, `add_source_ex`, and display metadata.
- The catalog is not a static 540-item list in smali/resource XML. Exact catalog
  names such as `Sunset Rush`, `Voltage Rage`, and `Mess & Glitch` are absent
  from the APK smali/resource search.
- The APK contains the renderer/protocol and only the local animation payloads
  `assets/epilogue_anim.zip` and `assets/curve_text_new.zip`.
- `assets/text_anim_icon_lottie.json` and `assets/text_anim_images/img_0..2.png`
  are UI assets, not the catalog effects.
- Runtime items provide a prospective local destination under
  `/data/user/0/com.lemon.lvoverseas/files/effect/`, but the 540 zips are not
  present yet. The `effect/` directory currently contains only text-template
  and typeface support files.

## Conclusion

CapCut ships the text-animation engine and protocol in the APK. The named
catalog is dynamic server metadata. Individual effect packages are downloaded
from the CDN and cached under the app's `files/effect` directory when selected.

## Files

- `capcut-text-animations-all.json`: full structured runtime dump.
- `capcut-text-animations-all.tsv`: one row per category/effect for quick
  filtering.
- `capcut-text-animations-in149-scan.json`: raw In/Out scan.
- `capcut-text-animations-loop198-scan.json`: raw Out/Loop scan.
- `capcut-anim-panel-runtime.png`: runtime Animations panel.

## Reproduction

1. Start `frida-server` as root on `emulator-5556`.
2. Open a text animation panel in CapCut.
3. Run:

```bash
frida -D emulator-5556 -p <capcut-pid> \
  -l tools/frida/dump-text-anim-live.js -q -t 8 \
  > /tmp/textanim-live-output.txt
```

The adapter can also be inspected live through `TextAnimAdapter.n` and
`TextAnimAdapter.j`.
