# alula branding

All alula browser-name text uses lowercase `alula`, including when it begins a
sentence. Internal source identifiers and the `out/Alula` build-directory name
are not user-facing branding and remain unchanged.

The branding patch series covers:

- macOS app/product name, executable, framework/helpers, About and Settings;
- remaining common Settings and profile descriptions;
- Password Manager and Keychain-access explanation text;
- extension onboarding/tips, download/security/permission notifications;
- shared error-page, session-restore, flags and Bluetooth prompts;
- visible wording on Accessibility and Bluetooth internal diagnostic pages.

## Names intentionally retained

Keep Chrome Web Store, Chrome Root Store/Program, Google Password Manager,
Google help/download destinations, Chrome mobile products, third-party Chrome
installations and Chromium attribution accurate. Preserve technical addresses,
resource IDs, translation examples, markup/links, file formats and protocols.
The existing Chromium icon remains, so its upstream identity/credits are not
removed. Google-branded/testing and non-Mac branches are not renamed by the
second branding patch.

Bundle/profile/Keychain identities are unchanged: `org.chromium.Chromium`, the
Chromium profile directory, and `Chromium Safe Storage`. Separating these needs
a deliberate future migration; a text branding pass must not move user data.

## Validation of the common-UI pass

- 137 message definitions and two internal HTML pages updated in 11 files.
- Before/after checks allowed only browser-name word substitutions.
- XML/HTML structure, attributes, IDs, links, placeholders, translator examples,
  protected service names and inactive platform/branded branches preserved.
- Existing product/short-name/About branding rechecked for lowercase `alula`.
- Affected GRIT/WebUI resource generation passed (13 actions, about 11 seconds).
- All three generated string resource-ID headers remained byte-for-byte equal.
- Compiled English packs checked for new labels, lowercase spelling, preserved
  Chrome Web Store/Root Store names, and Chromium project attribution.
- Internal page resource packs contain the new text.
- Patch replay checked separately against files from the pinned upstream base.

This pass changes English source strings. Translation catalogs were not
rewritten; changed strings can fall back to English where translations are
unavailable. This does not promise that every mention of Chrome in every
language or optional feature is replaced.

The validation builds resources only. Quit the browser, run
`python3 build_alula.py`, and relaunch `src/out/Alula/alula.app` to update the
running app. Check Settings/theme labels, Password Manager, extension tips,
notifications as encountered, and the Accessibility/Bluetooth internal pages.
