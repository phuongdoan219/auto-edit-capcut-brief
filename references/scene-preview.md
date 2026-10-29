# Rough cut first, selections second

Step 1 belongs to the editing agent: resolve source ranges and supplied voice/music, compose shots/layout/speed/transitions and requested effects, and export a rough cut without the pending native text/sticker choices. Keep the source mapping and an editable native plan. The preview helper does not implement arbitrary brief instructions or silently fill missing music/effects.

Prepare the reviewed request and plan with `workflow.py prepare ... --plan <plan.json> --base <base> --roughcut <roughcut.mp4>`. For a prepared work folder, run `python scripts/scene_preview.py --work <work> --video <roughcut.mp4>`. FFmpeg/ffprobe and Pillow are required. The rough cut must match the plan canvas and timings. Every slot needs final-plan placements, including optional stickers. The helper extracts stills at text visibility changes and representative scene moments into `scene-stills/`, then writes `scene-preview.json` with request/plan/rough-cut hashes. Work files and media never belong in Git.

The popup shows the current task, a rough-cut frame, the choices and the same Back + Continue/Skip actions. The Preview moment slider selects prepared moments. Clicking a tile updates only the preview and browser draft. Text from other selected slots in this scene is included when active at this moment. One effect slot can drive several sequential bullet text segments; each segment keeps its own time and transform. Skip does not render an optional sticker. Final review remains the only confirmation action.

`GET /api/scene-preview?frame=<id>&sample=<index>&choices=<scene choices>` uses the normal bearer token, validates frame/slot/category and uses allowlisted server-side data; there is no path parameter. It returns an in-memory JPEG. No route runs FFmpeg, edits a project, writes a choice, or starts a build. A stale plan/request or missing stills must be regenerated before launch. Do not pass choices from other scenes to this endpoint.

This is an **approximate layout preview**. It uses the chosen effect donor's local font, plain color/border, planned text, timing, position/scale/rotation/alpha. CapCut text size/layout, texture/glow/3D effect shaders, masks/keyframes and sticker size/motion cannot be reproduced exactly by Pillow. Sticker preview uses a readable frame from its own preview media; video-only sticker previews can report unavailable in the composite. Native sample thumbnails remain visible for appearance comparison. Display the approximation notice; do not claim an exact CapCut render. For native fidelity, stage the selected draft and inspect/render in CapCut through a supported verified path.

## How a choice reaches the edit

For a new revision with the same request/library, `prepare --reuse-selection <old/selection.json>` restores only validated previously confirmed human choices as a draft. The new session stays pending and requires Confirm & Edit again. It does not invent a default, copy choices from another brief, or overwrite the old confirmed session. A browser draft takes precedence when the user has already changed the revision.

- A tile click or Continue stores `{choices,wizard_step}` in browser localStorage, scoped by the request/library hashes. This does not submit a build decision.
- Confirm & Edit sends `{choices,request_hash,library_hash}` to the local authenticated `POST /api/confirm` endpoint. Keys map to stable slot IDs, not screenshot positions or translated names.
- The server revalidates category, resource availability, required slots, session hashes and machine. It atomically writes the confirmed `selection.json`; the browser only reports success after that write.
- A running `workflow.py run --work <work>` worker polls the file, validates it again, produces `edit-plan.selected.json` and builds the staged native draft. Without a worker, the agent calls `picker_server.py status/wait` and `workflow.py resume` on the next active turn.
- The popup does not inject a new message into ChatGPT/Codex and does not wake an ended model turn. A background worker can finish its deterministic build while chat is idle; discussion, app verification and additional creative editing resume in an active turn.
- Installation into a live project and verification in CapCut retain their existing checks. Never present a successful JSON build as a verified native render.
