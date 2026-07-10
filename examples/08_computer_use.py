"""
Example 08 — computer use & hosted sandboxes: the loop, pointed at a screen.
============================================================================

Computer use is the same agent loop with a different tool surface. Instead of
`calculator` / `read_file`, the tools are `screenshot`, `click`, and `type`, and
the "observation" fed back each step is an image of a screen. The model looks at
the screenshot, picks the next action, your harness performs it, takes a new
screenshot, and loops — exactly the observe → act → observe cycle you already know.

This example is a self-contained **simulation** of that loop (offline, no model,
no GUI): a tiny mock login form, a scripted "planner" standing in for the model,
and a harness-style step loop. It exists to show the *shape* — the real thing swaps
the scripted planner for a vision model and the mock screen for a real desktop or
browser.

Where a harness earns its keep here: the screen and the mouse live *somewhere*, and
you do not want that somewhere to be your laptop for an untrusted agent. Providers
offer a **hosted sandbox** — a throwaway VM/browser they run — so the computer-use
loop drives an isolated machine, not yours. That's the sandbox idea from example 05,
scaled up to a whole environment the provider hosts.

Run it:

    python examples/08_computer_use.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from harness import describe, ensure_ready

load_dotenv()
ensure_ready()
print(f"Provider: {describe()}\n")


# --- A tiny mock "screen": a login form with two fields and a button. -------
class MockScreen:
    def __init__(self):
        self.fields = {"username": "", "password": ""}
        self.focus = "username"
        self.logged_in = False

    def screenshot(self) -> str:
        """Stand-in for an image — a text description of the current screen."""
        u = self.fields["username"] or "(empty)"
        p = "•" * len(self.fields["password"]) or "(empty)"
        if self.logged_in:
            return "SCREEN: Dashboard — 'Welcome back!'"
        return f"SCREEN: Login form. username=[{u}] password=[{p}] focus={self.focus} [Sign in]"

    def apply(self, action: str, arg: str = "") -> None:
        if action == "click" and arg == "username":
            self.focus = "username"
        elif action == "click" and arg == "password":
            self.focus = "password"
        elif action == "type":
            self.fields[self.focus] += arg
        elif action == "click" and arg == "Sign in":
            if self.fields["username"] and self.fields["password"]:
                self.logged_in = True


def scripted_planner(screenshot: str) -> tuple[str, str]:
    """Stand-in for a vision model: read the screenshot, choose the next action.
    A real computer-use model returns this same (action, arg) shape from an image."""
    if "Dashboard" in screenshot:
        return ("done", "")
    if "username=[(empty)]" in screenshot:
        return (
            ("type", "dana")
            if "focus=username" in screenshot
            else ("click", "username")
        )
    if "password=[(empty)]" in screenshot:
        return (
            ("type", "hunter2")
            if "focus=password" in screenshot
            else ("click", "password")
        )
    return ("click", "Sign in")


screen = MockScreen()
goal = "Log in as dana."
print(f"Goal: {goal}\n")
print("Observe → act → observe loop:")

for step in range(8):
    shot = screen.screenshot()  # 1. observe (a "screenshot")
    print(f"  step {step}: {shot}")
    action, arg = scripted_planner(shot)  # 2. model picks an action
    if action == "done":
        print(f"  step {step}: goal reached — the agent stops.")
        break
    print(f"           -> action: {action} {arg!r}")
    screen.apply(action, arg)  # 3. harness performs it; loop re-observes

print(
    "\nThat's computer use: the exact observe → act → observe loop from the rest of\n"
    "this dive, with a screen as the observation and click/type as the tools. Two\n"
    "things a harness adds that a bare script can't: the same permission and hook\n"
    "seams (gate a `click Submit` on a payment page; redact a password from the\n"
    "action log), and a HOSTED SANDBOX — a provider-run VM/browser so the agent\n"
    "drives an isolated machine, never your own. Reach for it when the task lives in\n"
    "a GUI with no API; prefer a real tool/API whenever one exists (it's cheaper and\n"
    "far more reliable than driving pixels)."
)
