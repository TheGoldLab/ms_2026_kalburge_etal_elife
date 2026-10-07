# PigeonTask (MXSC)

A PsychoJS pigeon-tracking decision task ("Petey" random-walks toward a left/right seed
pile; the participant predicts which pile he'll end up at). See the file header of
[PigeonTask.js](PigeonTask.js) for the full task design and session flow. This is a
PsychoPy-Builder-exported project (`PigeonTask.psyexp` compiles to `PigeonTask.js`), meant
to be deployed via [Pavlovia](https://pavlovia.org).

## 1. Running locally in a browser

You can't just double-click `index.html` — `PigeonTask.js` is loaded as an ES module
(`<script type="module">`) and fetches its `Resources/*.xlsx`/images at runtime, both of
which browsers block under the `file://` protocol. You need a local static server:

```bash
cd task/MXSC
python3 -m http.server 8934
```

Then open `http://localhost:8934/index.html`. (Any static file server works — `npx serve .`
or the VS Code "Live Server" extension are fine substitutes if you don't have Python.)

What to expect:
- A participant-info dialog pops up first (participant ID, session). Enter anything and
  click OK.
- The task requests real browser fullscreen (`fullscr: true`,
  [PigeonTask.js:124](PigeonTask.js#L124)). If your browser blocks the fullscreen
  request or you exit it mid-session, the task keeps running windowed; if the window then
  gets narrower than ~1.6x its height, a "please widen your window" overlay covers the
  task instead of showing a broken/clipped layout (see
  [PigeonTask.js:130-159](PigeonTask.js#L130-L159) — this task's layout assumes a
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

## 2. Running via Prolific

Prolific studies need a hosted URL, and PsychoJS only auto-saves data server-side (and only
gates on experiment status/credits) when it's actually running from a `pavlovia.org` /
`run.pavlovia.org` host — so real data collection goes through Pavlovia, not a plain web
server.

1. **Sync the project to Pavlovia.** From PsychoPy Builder, open `PigeonTask.psyexp` and use
   its "sync with Pavlovia" button (or upload the `task/MXSC/` contents directly via the
   pavlovia.org web UI). This creates/updates a project at
   `https://pavlovia.org/<your-username>/<project-name>`.
2. **Set the project's running mode** on its pavlovia.org project page to `PILOTING` (free,
   for testing — no data saved for real, or saved to a piloting-only area depending on your
   Pavlovia settings) or `RUNNING` (real data collection; requires the project to have
   assigned credits, since PsychoJS's server manager checks for exactly this before letting a
   session start).
3. **Build the Prolific Study URL** pointing at `https://run.pavlovia.org/<your-username>/<project-name>/`,
   with Prolific's placeholder variables appended as query params so they land in `expInfo`
   via `util.addInfoFromUrl` ([PigeonTask.js:269](PigeonTask.js#L269), which copies every URL
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
   ([PigeonTask.js:270](PigeonTask.js#L270)). Set your Prolific study's completion code to
   `C1MSKA9I`, or edit that line if you're using a different code for this study.
5. **Retrieve data** from the project's pavlovia.org page (downloadable as CSV/zip) rather
   than from participants' local downloads — `SERVER` environment sessions don't trigger a
   browser download the way local runs do.
