"""Resize Nurse.ng's existing mark for native launchers; no new branding."""

from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
icon = Image.open(root / "resources/app-icon.png").convert("RGBA")
android = root / "android/app/src/main/res"
for path in android.glob("mipmap-*/*.png"):
    with Image.open(path) as original:
        size = original.size
    if "foreground" in path.name:
        output = Image.new("RGBA", size)
        mark_size = int(size[0] * .62)
        mark = icon.resize((mark_size, mark_size), Image.Resampling.LANCZOS)
        output.alpha_composite(mark, ((size[0] - mark_size) // 2, (size[1] - mark_size) // 2))
    else:
        output = icon.resize(size, Image.Resampling.LANCZOS)
    output.save(path)
icon.convert("RGB").save(root / "ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png")
for path in list(android.glob("drawable*/splash.png")) + list(
    (root / "ios/App/App/Assets.xcassets/Splash.imageset").glob("*.png")
):
    with Image.open(path) as original:
        size = original.size
    output = Image.new("RGB", size, "#073c40")
    mark_size = max(32, int(min(size) * .18))
    mark = icon.resize((mark_size, mark_size), Image.Resampling.LANCZOS)
    output.paste(mark, ((size[0] - mark_size) // 2, (size[1] - mark_size) // 2), mark)
    output.save(path)
(android / "values/ic_launcher_background.xml").write_text(
    '<resources><color name="ic_launcher_background">#007e73</color></resources>\n'
)
