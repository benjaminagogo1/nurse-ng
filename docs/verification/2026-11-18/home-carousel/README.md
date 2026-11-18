The homepage now shows “Better Care, Together.” immediately after the original
careers hero. The pre-change page contained one static hero; that hero's content,
search form, links, photography and styling remain the first slide.

The second slide uses a crop of the supplied `second.png` showing the central
patient and all four healthcare professionals. Its headline, supporting sentence,
care concepts and closing statement are HTML text. Three local WebP sizes provide
responsive images; the largest is 94,988 bytes. Printed image pagination dots were
removed so navigation uses the actual carousel controls.

The homepage controller provides ten-second autoplay, a 480 ms fade, previous/next
buttons, two indicators, keyboard navigation and Play/Pause. Navigation resets the
ten-second timer without turning autoplay off. A pointer resting over the homepage
does not pause rotation; focusing the search or a slide link stops it until Play is
selected. Reduced motion starts paused and disables the fade. Initial slide
visibility is committed before fades are enabled to prevent a flash on refresh.
Both messages remain available without JavaScript.

The isolated Chrome check passed at 1440, 1024, 768, 390 and 320 pixels. It verified
the original hero against its pre-change HTML and height, the second slide's order,
fade interpolation, stable page geometry, navigation, actual autoplay/pause/resume,
keyboard focus, responsive image loading, enlarged text, high contrast, reduced
motion and the no-JavaScript fallback. No JavaScript exceptions or broken assets
were recorded. The existing anonymous `/offline/session` 401 response is expected
and excluded from broken-asset reporting.

The rotation regression was reproduced before the fix by moving a real mouse
pointer over the hero: the second slide never appeared within 13 seconds. The
browser runner now checks real mouse clicks, rendered opacity after the fade,
continued visibility through the slide interval, and Play with the pointer still
over the control. Arrow/dot navigation continues autoplay, and search focus pauses
it. Use `--rotation-only` to repeat these focused checks without the layout captures.

The full Python suite passed (1,064 tests, including the two homepage tests and
seven recruitment TLS tests). Ruff for app/tests, JavaScript syntax validation
and `git diff --check` passed.

[Desktop preview](desktop.png) · [Mobile preview](mobile.png) ·
[Browser check report](report.json)

Repeat the functional browser check from the repository root:

```sh
venv/bin/python tests/browser/home_carousel.py
```

The runner uses the installed Chrome and existing Python environment, creates an
isolated temporary server/browser profile, and reports its artifact directory.

To check the running local app with a separate browser profile:

```sh
venv/bin/python tests/browser/home_carousel.py --url http://127.0.0.1:8000
```
