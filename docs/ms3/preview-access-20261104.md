# Preview access and reproduction

The current Reading Desk is A `20261104.3`. The [UX report](connections-ux-20261104.md) records actual interaction checks and limitations.

## Durable review

A separate ChatGPT Site was published at:

https://tastebridge-reading-desk-20261104.landenini.chatgpt.site

Its current audience is owner-only. Broader link access is awaiting an explicit audience choice. The in-app browser reached the sign-in gate, but OpenAI account selection returned a platform route error; hosted interaction QA has not yet completed. The original shared prototype Site and its data were not modified.

[Read-only hosted HTTP checks](site-http-20261104.json) returned 200 for `/`, `/a/`, `/b/` and `/project/` using the platform's Site-scoped service access. Each delivered page preserves its entire original source with an additional hosting insertion. This verifies delivery of the packaged prototype; it does not establish visitor login or interaction success. No service credential is included in this record or the Site source.

This static Site contains only the 23-book frontend demo, comparison B and the project overview. It has no trained backend, data export, account database or feedback collection.

## Rebuild offline A/B

From `frontend/prototype`:

```sh
node scripts/build-prototype.mjs
node scripts/verify-release.mjs
```

The self-contained files are `.prototype-build/TasteBridge-Prototype-A.html` and the B sibling. Open A in a browser for the core offline flow. Keep both files together for A/B navigation. The generated files' Project links and API mode require HTTP hosting.

A user-specific ZIP with local project navigation was delivered separately; private download identities and machine-specific paths are intentionally omitted here.

## Connected local preview

From `frontend/prototype`, in a terminal you keep open:

```sh
TASTEBRIDGE_UI_PORT=4180 TASTEBRIDGE_API_PORT=9020 node scripts/dev.mjs
```

Open `http://127.0.0.1:4180/a/?api=0` for the offline sample or `?api=1` for the bundled API. Do not start a duplicate if those ports are already occupied. Ctrl-C stops both services.

The task-managed server did not survive task completion; a detached `nohup` attempt also did not persist. A localhost address is therefore not the durable handoff. During verification, frontend health was OK and the API reported `sample-shelf-toy-v1`, `hand-curated-sample-52`, 52 books. The owned test services were stopped after checks.

## Tool limits

Native Terminal-app control was denied. In-app browser navigation to `file://` was denied by its URL policy; the action was stopped and not bypassed. Earlier Chrome automation could verify title/navigation but not rendered interactions. Local browser flow checks used supported loopback HTTP. No browser security, credential, permission or system-service settings were changed.
