# PigeonTask (RC: reward change)

A PsychoJS pigeon-tracking decision task ("Petey" random-walks toward a left/right seed
pile; the participant predicts which pile he'll end up at), meant to be deployed via
[Pavlovia](https://pavlovia.org). See the file header of [PigeonTask.js](PigeonTask.js)
for the full task design and session flow.

**Design.** Four 1000-step blocks, all at the same difficulty (step mean 0.01, SD 0.05).
Every trial costs 1 step to start (as in MXSC; not shown to participants), and every error costs 15
extra steps. The error charge is the one cost participants need to weigh: without it the reward-rate
optimum is to respond after 1–2 steps, which leaves the falling-reward block nothing to test; a start
cost alone does the same job but costs more trials (notebooks/design/Design_rcTask.ipynb).

Bonus targets are the simulated median coins per block (notebooks/design/Design_rcTask.ipynb, section 4),
rounded to a multiple of 5, so about half of participants should reach each one.

| Block (`tc_block_type`) | Coins (correct / error) | Bonus target |
|---|---|---|
| `fixed_low` | +1 / -1 (cactus icon) | 25 |
| `fixed_high` | +3 / -3 (tree icon) | 70 |
| `change_low` (rising reward) | +1 / -1, then +3 / -3 from the switch step on | 55 |
| `change_high` (falling reward) | +3 / -3, then +1 / -1 from the switch step on | 55 |

The two fixed blocks run first in random order, then the two change blocks in random
order (saved in the `block_order` column). The switch step is the participant's median
response time over both fixed blocks pooled (first 10 responses of each dropped). It is
the same in both change blocks, with a countdown bar under the icon. All settings live in
`Resources/PigeonTaskConditions.xlsx`.

**Derived from `task/MXSC`, edited by hand.** MXSC's PsychoPy Builder file is obsolete
(the JS was fixed and redesigned directly), so this project has no `.psyexp`. Edit
`PigeonTask.js` directly, and never regenerate it from Builder. There is also no
legacy-browser build (`PigeonTask-legacy-browsers.js`), since MXSC's was stale.

## 1. Running locally in a browser

You can't just double-click `index.html` — `PigeonTask.js` is loaded as an ES module
(`<script type="module">`) and fetches its `Resources/*.xlsx`/images at runtime, both of
which browsers block under the `file://` protocol. You need a local static server:

```bash
cd task/RC
python3 -m http.server 8934
```

Then open `http://localhost:8934/index.html`. (Any static file server works — `npx serve .`
or the VS Code "Live Server" extension are fine substitutes if you don't have Python.)

What to expect:
- A participant-info dialog pops up first (participant ID, session). Enter anything and
  click OK.
- The task requests real browser fullscreen (`fullscr: true`,
  [PigeonTask.js:131](PigeonTask.js#L131)). If your browser blocks the fullscreen
  request or you exit it mid-session, the task keeps running windowed; if the window then
  gets narrower than ~1.6x its height, a "please widen your window" overlay covers the
  task instead of showing a broken/clipped layout (see
  [PigeonTask.js:137-170](PigeonTask.js#L137-L170) — this task's layout assumes a
  landscape-ish window and doesn't reflow to other aspect ratios).
- Since `localhost` isn't a Pavlovia host, PsychoJS runs in its `LOCAL` environment: at the
  end of the session your data is offered as a CSV **download** (goes to your browser's
  default download folder) rather than saved to a server. Handy for quick local testing;
  you don't need a Pavlovia account for this.
- To skip typing a participant/session ID on every test run, append them as URL query
  params instead — e.g. `http://localhost:8934/index.html?participant=test&session=001`.
  Any dialog field whose name matches a URL param (case-insensitive) is silently dropped
  from the popup (verified: with both `participant` and `session` supplied, the dialog
  shows only a resource-loading bar and OK/Cancel, no text fields). This is the same
  mechanism the Prolific integration below relies on.
- To test a whole session quickly, add `test_steps_max` to shorten every block, e.g.
  `http://localhost:8934/index.html?participant=test&session=001&test_steps_max=250`. It is
  saved in every data row (with the other URL parameters), so test sessions are easy to
  recognize. Never include it in the Prolific URL.

## 2. Running via Prolific

Prolific studies need a hosted URL, and PsychoJS only auto-saves data server-side (and only
gates on experiment status/credits) when it's actually running from a `pavlovia.org` /
`run.pavlovia.org` host — so real data collection goes through Pavlovia, not a plain web
server.

1. **Upload the project to Pavlovia.** Upload the `task/RC/` contents (including `lib/`)
   through the pavlovia.org web UI, or push them to the project's Pavlovia git repository.
   Don't use PsychoPy Builder's "sync" button, which would regenerate `PigeonTask.js`. This
   creates/updates a project at `https://pavlovia.org/<your-username>/<project-name>`.
2. **Set the project's running mode** on its pavlovia.org project page to `PILOTING` (free,
   for testing — no data saved for real, or saved to a piloting-only area depending on your
   Pavlovia settings) or `RUNNING` (real data collection; requires the project to have
   assigned credits, since PsychoJS's server manager checks for exactly this before letting a
   session start).
3. **Build the Prolific Study URL** pointing at `https://run.pavlovia.org/<your-username>/<project-name>/`,
   with Prolific's placeholder variables appended as query params so they land in `expInfo`
   via `util.addInfoFromUrl` ([PigeonTask.js:271](PigeonTask.js#L271), which copies every URL
   query param into `expInfo` by key name) and pre-fill/hide the matching dialog fields
   exactly as tested locally above:
   ```
   https://run.pavlovia.org/<your-username>/<project-name>/?participant={{%PROLIFIC_PID%}}&session={{%STUDY_ID%}}
   ```
   With this, participants never see a participant-ID field to type into — just a brief
   resource-loading dialog — and the `participant` column in your exported data will be
   their actual Prolific ID.
4. **Match the completion code.** On finishing, the task redirects to
   `https://app.prolific.com/submissions/complete?cc=C1MSKA9I`
   ([PigeonTask.js:272](PigeonTask.js#L272)). That is the MXSC study's code: replace it with
   the new Prolific study's completion code before running.
5. **Retrieve data** from the project's pavlovia.org page (downloadable as CSV/zip) rather
   than from participants' local downloads — `SERVER` environment sessions don't trigger a
   browser download the way local runs do.
