"""look_at_screen: one screenshot, on request only, sent to the model as an image."""
import base64
import io

from bot.tools.base import err, ok, queue_conversation_item, tool

MAX_SIDE = 1280
JPEG_QUALITY = 70


def capture_jpeg() -> tuple[bytes, int, int]:
    """Grab the screen, downscale so the longest side is ~1280 px, encode as JPEG."""
    from PIL import ImageGrab  # Pillow ships with fpdf2

    image = ImageGrab.grab()
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), image.width, image.height


@tool(
    "look_at_screen",
    "Take one screenshot of Gopi's screen so you can see it. Use when he says 'this', "
    "'here', 'on my screen', 'what am I looking at', or when a task needs to see what's "
    "on screen. Pass his question. The screenshot arrives as the next message; answer from it.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What Gopi wants to know about the screen."},
        },
    },
)
def look_at_screen(question: str | None = None) -> str:
    try:
        jpeg, width, height = capture_jpeg()
    except Exception as e:
        return err(f"couldn't capture the screen: {type(e).__name__}: {e}")
    prompt = "This is a screenshot of Gopi's screen, taken just now."
    if question:
        prompt += f" His question: {question}"
    queue_conversation_item(
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()},
                {"type": "input_text", "text": prompt},
            ],
        }
    )
    return ok(captured=True, width=width, height=height, kb=len(jpeg) // 1024,
              note="Screenshot attached as the next message.")
