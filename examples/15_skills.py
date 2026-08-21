"""
Example 15: Agent Skills, or how you scale instructions without bloating context.

By §7 you had subagents, and by §14 you had a hosted harness. Both solve a
version of the same problem: a capable agent needs more instructions than fit
comfortably in one system prompt, and stuffing everything in makes every request
slower, dearer, and (per the context dive) measurably worse.

A **skill** is the instruction-set answer to that problem. It is a folder with a
`SKILL.md` inside: a short description plus however much procedure you want.
The description sits in context always; the body is read only when the model
judges the task calls for it. That is **progressive disclosure**, and it is the
same trick tool search plays for tool schemas.

  system prompt   always in context, every request, forever
  skill           one line in context; the rest loaded on demand
  subagent (§7)   a whole separate context window, for work not instructions

WHAT IT LOOKS LIKE ON THE WIRE
    Skills run inside the code-execution container, so a skill request is three
    things together, and it fails if you omit any of them:

        betas=["code-execution-2025-08-25", "skills-2025-10-02"]
        container={"skills": [{"type": "anthropic", "skill_id": "xlsx"}]}
        tools=[{"type": "code_execution_20260521", "name": "code_execution"}]

    Anthropic ships four: `xlsx`, `pptx`, `docx`, `pdf`. You can list them with
    `client.beta.skills.list(betas=["skills-2025-10-02"])`, and register your own
    against the same endpoint.

WHY THIS BELONGS IN A HARNESS DIVE
    A skill is not a model capability. It is *configuration your harness owns*,
    exactly like the permission policy in §5 or the tool surface in §4. The
    decisions are yours: which skills to attach, whether the model may reach for
    one unprompted, and what happens to the files it writes. Everything this dive
    says about auditing what an agent can do applies here, because a skill can
    carry scripts, and those scripts run.

    That last point is worth sitting with. A skill loaded from a repository is
    instructions with execution attached. Treat one you did not write with the
    same suspicion as a tool you did not write.

Costs a little (code execution plus tokens), so it is opt-in:

    python examples/15_skills.py               # explain + list skills, free
    secrun python examples/15_skills.py --real # actually build a spreadsheet
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REAL = "--real" in sys.argv
SKILL_BETAS = ["code-execution-2025-08-25", "skills-2025-10-02"]
MODEL = "claude-sonnet-4-6"


def main() -> None:
    print(__doc__.strip())

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\n(no ANTHROPIC_API_KEY, so stopping here. See ../docs/SECRETS.md.)")
        return

    import anthropic

    client = anthropic.Anthropic()

    # Listing skills is free, so we always do it: it proves the account has them
    # and shows the shape of the registry your harness would choose from.
    print("\n--- skills available to this account ---")
    for skill in client.beta.skills.list(betas=["skills-2025-10-02"]).data:
        print(f"  {skill.id}")

    if not REAL:
        print(
            "\nStopping before the paid part. Re-run with --real to have the\n"
            "xlsx skill actually build a spreadsheet:\n"
            "    secrun python examples/15_skills.py --real"
        )
        return

    # --- the paid part: attach a skill and let it work ----------------------
    print(f"\n--- attaching the xlsx skill on {MODEL} ---")
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=8192,
        betas=SKILL_BETAS,
        container={"skills": [{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}]},
        tools=[{"type": "code_execution_20260521", "name": "code_execution"}],
        messages=[
            {
                "role": "user",
                "content": (
                    "Build a small spreadsheet named costs.xlsx with columns "
                    "Model, InputPerMTok, OutputPerMTok and three rows: "
                    "gpt-5.4-nano 0.20 1.25; claude-haiku-4-5 1.00 5.00; "
                    "claude-opus-5 5.00 25.00. Then tell me you are done."
                ),
            }
        ],
    )

    # The response interleaves the model's text with the container's work. Note
    # that YOU never ran the code: this is the same "hosted tool" shape as §9's
    # hosted sandboxes, with the skill supplying the know-how.
    print("\nblocks the API produced:")
    for block in response.content:
        print(f"  - {block.type}")

    text = "".join(b.text for b in response.content if b.type == "text")
    if text:
        print(f"\nmodel said: {text.strip()[:300]}")

    # Files the skill produced come back through the Files API, not inline.
    file_ids = []
    for block in response.content:
        if block.type == "bash_code_execution_tool_result":
            content = getattr(block, "content", None)
            for ref in getattr(content, "content", None) or []:
                fid = getattr(ref, "file_id", None)
                if fid:
                    file_ids.append(fid)

    if file_ids:
        print("\nfiles the skill created:")
        for fid in file_ids:
            meta = client.beta.files.retrieve_metadata(fid, betas=["files-api-2025-04-14"])
            print(f"  {meta.filename} ({meta.size_bytes} bytes)  id={fid}")
        print(
            "\nDownload with client.beta.files.download(file_id). The artifact is\n"
            "the point: the model did not describe a spreadsheet, it produced one."
        )
    else:
        print(
            "\nNo file ids surfaced on this run. The skill may have finished inside\n"
            "the container without emitting an output block; re-run, or list files\n"
            "for the container. The lesson is unchanged: artifacts come back via\n"
            "the Files API, never inline in the message."
        )


if __name__ == "__main__":
    main()
