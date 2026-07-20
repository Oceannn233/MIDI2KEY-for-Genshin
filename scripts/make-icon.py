"""Build reproducible Windows and web icons from the master transparent PNG."""

from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "assets" / "app-icon.png"
ICO_OUTPUT = PROJECT_ROOT / "assets" / "app-icon.ico"
WEB_OUTPUTS = (
    PROJECT_ROOT / "public" / "app-icon.png",
    PROJECT_ROOT / "local_app" / "web" / "icon.png",
)
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main() -> None:
    image = Image.open(SOURCE).convert("RGBA")
    if image.width != image.height:
        raise ValueError("The master app icon must be square.")

    alpha = image.getchannel("A")
    corners = (
        alpha.getpixel((0, 0)),
        alpha.getpixel((image.width - 1, 0)),
        alpha.getpixel((0, image.height - 1)),
        alpha.getpixel((image.width - 1, image.height - 1)),
    )
    if any(value > 8 for value in corners):
        raise ValueError("The master app icon must have transparent corners.")

    image.save(ICO_OUTPUT, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    web_icon = image.resize((512, 512), Image.Resampling.LANCZOS)
    for output in WEB_OUTPUTS:
        output.parent.mkdir(parents=True, exist_ok=True)
        web_icon.save(output, format="PNG", optimize=True)

    print(f"Created {ICO_OUTPUT.relative_to(PROJECT_ROOT)}")
    for output in WEB_OUTPUTS:
        print(f"Created {output.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
