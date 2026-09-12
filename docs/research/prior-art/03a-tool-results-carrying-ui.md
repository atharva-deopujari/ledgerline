# Tool results that carry renderable UI: MCP-UI / MCP Apps, OpenAI Apps SDK, Adaptive Cards

Partial input to `03-generative-ui-cards.md`. Researched 2026-09-12. Three protocols where a tool result
carries something the host renders, compared against Ledgerline's full-snapshot cards over Daily app-message.

## (A) MCP-UI / MCP Apps

- Repo: https://github.com/MCP-UI-Org/mcp-ui (was idosal/mcp-ui), ~5,146 stars, last commit 2026-07-08, docs https://mcpui.dev
- What: SDK + wire convention for MCP tool results that return an embeddable `UIResource` (`ui://…` HTML) rendered in a sandboxed iframe, talking to the host over JSON-RPC-on-`postMessage`. Converged onto the MCP Apps standard (`@modelcontextprotocol/ext-apps`).

UIResource shape (`docs/src/guide/protocol-details.md`):
```ts
export interface UIResource {
  type: 'resource';
  resource: { uri: string; mimeType: 'text/html;profile=mcp-app'; text?: string; blob?: string };
}
```
`sdks/typescript/server/src/types.ts`:
```ts
export type ResourceContentPayload =
  | { type: 'rawHtml'; htmlString: string }
  | { type: 'externalUrl'; iframeUrl: string };

export const UIMetadataKey = {
  PREFERRED_FRAME_SIZE: 'preferred-frame-size',
  INITIAL_RENDER_DATA: 'initial-render-data',
} as const;
```
`initial-render-data` is the first-paint payload, analogous to Ledgerline's initial full snapshot.

Protocol shape, most liftable part. MCP Apps splits host to guest into typed notifications, not one blob:

| Host to guest | Guest to host |
|---|---|
| `ui/notifications/tool-input` (complete args) | `tools/call` |
| `ui/notifications/tool-input-partial` (streaming partial args) | `ui/message` (follow-up to conversation) |
| `ui/notifications/tool-result` | `ui/open-link` |
| `ui/notifications/host-context-changed` (theme, locale, viewport) | `notifications/message` |
| `ui/notifications/size-changed`, `tool-cancelled`, `ui/resource-teardown` | `ui/notifications/size-changed` |

Legacy action vocabulary (`docs/src/guide/embeddable-ui.md`), worth copying for any card action buttons: `intent` (user expressed intent, host acts), `notify` (iframe already acted, host runs side effects), `prompt`, `tool`, `link`.

Idempotency and correlation: explicit `messageId` request/response envelope, not a version counter:
```js
window.parent.postMessage({ type:'tool', messageId:'unique-request-id-123', payload:{…} }, '*');
// host acks:   { type: 'ui-message-received', messageId }
// host replies:{ type: 'ui-message-response', messageId, payload: { response } | { error } }
```
Docs: "Ensure `messageId` values are unique"; "Always clean up pending request tracking to avoid memory leaks." Lift: if Ledgerline ever adds card buttons, carry a client `messageId`, ack immediately (spinner), resolve or reject later. That is the confirm-badge lifecycle.

Size: no numeric cap documented. `text` for smaller content, `blob` (base64) for larger. Resizing is explicit and continuous via `ResizeObserver` and a `ui-size-change {height}` message.

Anti-patterns it warns about: `targetOrigin: '*'` without origin check on both sides; SSRF via server-side `externalUrl` fetch; hosts that silently ignore `baseUriDomains`.

## (B) OpenAI Apps SDK widgets

- Repo: https://github.com/openai/openai-apps-sdk-examples, ~2,326 stars, last commit 2026-04-15, docs https://developers.openai.com/apps-sdk
- What: ChatGPT-hosted React widgets bound to MCP tools via `_meta`, driven by a `window.openai` bridge that pushes host globals into the iframe.

`_meta` declarations (https://developers.openai.com/apps-sdk/reference): `openai/outputTemplate`, `openai/widgetAccessible`, `openai/toolInvocation/invoking` and `…/invoked` (each 64 characters max), `openai/widgetDescription`, `openai/widgetCSP`, `ui.prefersBorder`. Result-side host `_meta`: `openai/widgetSessionId` (stable id per mounted widget instance).

The bridge is a push-with-cache store, not a fetch. `src/types.ts` declares globals `toolInput / toolOutput / toolResponseMetadata / widgetState / setWidgetState / theme / locale / maxHeight / displayMode / safeArea`, plus `callTool`, `sendFollowUpMessage`, `requestDisplayMode`, and:
```ts
export const SET_GLOBALS_EVENT_TYPE = "openai:set_globals";
export class SetGlobalsEvent extends CustomEvent<{ globals: Partial<OpenAiGlobals> }> {}
```
`src/use-openai-global.ts` is the reconcile loop worth copying: `useSyncExternalStore` + module-level `cachedGlobals` + `Object.is` dedupe + a 250 ms poll, max 40 attempts (10 s), stopping on first value. An explicit resync path for the case where the widget mounts before the host has pushed state. Ledgerline analogue: browser joins after the first snapshot was sent, needs a "request latest snapshot" path.

Streaming and focus. `src/streaming-tool-input/App.tsx`: `ontoolinputpartial` sets phase `streaming`, `ontoolinput` gives final args, `ontoolresult` sets `complete`. Provisional values are rendered, not hidden, marked by styling only. Placeholder is literally `"..."` and trailing text is faded:
```tsx
{story.title !== undefined && (
  <h2 className={phase === "streaming" ? "text-gray-700" : "text-gray-900"}>
    {story.title || "..."}
  </h2>
)}
```
Phase also stated in words in a banner ("Streaming input…" / "Complete"), a cheap live-region equivalent. Lift: Ledgerline's `?` values equal the `"..."` pattern; `focus` equals the `phase === "streaming"` border and background swap on one card.

Documented size limits: widgetState "should not exceed 4k tokens" (https://developers.openai.com/apps-sdk/build/state-management); invoking/invoked strings 64 characters; `structuredContent` is model-visible, `_meta` is widget-only and hidden from the model. State-management splits `modelContent` ("text or JSON the model should see") from `privateContent` ("UI-only state the model should not see").

Anti-patterns explicitly named:
- "If you attach a widget template to every tool call, ChatGPT can re-render your iframe too often." Decoupled pattern: data tools return only `structuredContent`; only render tools carry the template.
- Storing business data only in the UI; using `localStorage` for core state; trusting component-computed totals, verify server-side.
- "Return enough structured content for both the model and UI to understand the new state. This also lets the conversation remain useful if the UI cannot load."
- Sync contract: UI calls tool, server validates and updates, server returns updated snapshot, "UI renders snapshot while preserving compatible presentation state."

## (C) Microsoft Adaptive Cards

- Repo: https://github.com/microsoft/AdaptiveCards, ~1,964 stars, last commit 2026-08-27, https://adaptivecards.io
- What: platform-neutral declarative JSON card schema with host-owned styling, no code-behind.

Update and refresh model (https://learn.microsoft.com/en-us/adaptive-cards/authoring-cards/universal-action-model, schema 1.4+):
```json
"refresh": {
  "action": { "type": "Action.Execute", "title": "Submit", "verb": "personalDetailsCardRefresh" },
  "userIds": []
}
```
`Action.Execute` fires an invoke carrying `value.trigger: "automatic" | "manual"`, so the card tells the server whether a human or an auto-refresh caused the update. The bot replies with a whole replacement card. Full-snapshot replacement, never a delta. `refresh.expires` (1.6) is an ISO-8601 staleness timestamp.

Scale guard: without `userIds`, the card will not auto-refresh; a manual refresh button is shown instead, because "an unconditional automatic refresh would result in many concurrent calls to the bot". Max 60 user ids.

Versioning and fallback, applicable to Ledgerline's `v` handshake: `version` is the schema version the card requires, lower clients render `fallbackText`; per-element `fallback` (an element, or `"drop"`) and `requires: {feature: minVersion}`.

Data binding (https://learn.microsoft.com/en-us/adaptive-cards/templating/language): `${…}` paths, "graceful null handling ensures you won't get exceptions if you access a null property"; `$data` bound to an array repeats the element per item; `$when: "${price > 30}"` drops an element; `"color": "${if(priceChange >= 0, 'good', 'attention')}"` is exactly the provisional/confirmed colour switch, expressed declaratively.

Host limits (Teams): cards v1.6 or earlier; images 1024x1024 max; connector cards max 10 sections, 5 images and 5 actions per section; carousel max 10 cards. Layout: "must not display a horizontal scroll, don't specify a fixed width"; at most 3 columns.

Accessibility (https://learn.microsoft.com/en-us/microsoft-copilot-studio/adaptive-card-accessibility-tips), all four map to Ledgerline cards:
- Always include `label`; placeholders are not labels.
- `"style": "heading"` marks a TextBlock as a heading for screen readers. Use for card titles.
- "Avoid `isVisible: false` for accessibility scenarios: screen readers skip hidden elements entirely." So the missing-info card should render missing fields as present-but-empty, not omitted.
- Tab order follows DOM order; avoid layouts whose visual order differs from DOM order.

Testing: the Adaptive Cards Designer (https://adaptivecards.microsoft.com/designer) edits template and sample data side by side. Process rule: "All new features are documented and associated with a test card published in the samples folder", one JSON fixture per feature, checked in. Validate with Narrator or NVDA, test in narrow form factors.

## Cross-cutting takeaways for Ledgerline

1. Full snapshot wins in all three. Adaptive Cards replaces the entire card; Apps SDK re-pushes `toolOutput` wholesale; mcp-ui re-sends the resource. None ship a delta protocol. Keep full snapshot plus `v`; drop anything `v <= current`; treat a gap as "request resync", never "apply anyway".
2. Two channels, not one. Model-visible (`structuredContent`) vs UI-only (`_meta`). Under the 4 KB cap, keep the model's tool-result string a terse fact list and put presentation detail in the card payload. Keep the text good enough that "the conversation remains useful if the UI cannot load".
3. Don't re-render on every tool call. One snapshot, one focused card animated, everything else reconciled in place by id.
4. Provisional means rendered and marked, never hidden. `"..."` plus faded text beats omission; `isVisible:false` is an accessibility trap. Pair `?` and the confirm badge with `aria-live="polite"` on the focused card only, and a phase word so a screen-reader user hears what the fade shows.
5. Correlate confirmations with ids. mcp-ui's `messageId`, `ui-message-received`, `ui-message-response` three-step is the cleanest confirm state machine if card buttons are ever added.
6. Reduced motion: none of the three documents a motion policy. Ledgerline needs its own `prefers-reduced-motion` rule; an unfilled gap, not something to copy.
