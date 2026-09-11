# Bonjour epta - release feed

Desktop translator for selected text: hit the hotkey, get the translation in a
mini card next to the cursor. Windows only.

**This repository is a release feed, not the source.** It carries the published
launcher and the update manifest, nothing else. Development happens in a
private repository.

## Install

1. Download **BonjourLauncher.exe** from the [latest release](https://github.com/test4testUnlimit/Bonjour-epta/releases/latest).
2. Run it. The launcher installs Python if it is missing, unpacks the app and
   starts it. No installer, no admin rights, nothing written outside your
   profile.

Windows SmartScreen may warn about an unsigned executable: *More info* ->
*Run anyway*.

## Updating

The app checks this feed on its own and offers the update in place. The
manifest ships as a release asset at `/releases/latest/download/latest.json`,
and the launcher asset always keeps the same unversioned name, so both URLs
are permanent.

## Where the data lives

Settings, logs and the acronym pack sit in `~/.bonjour-epta`. Nothing leaves
the machine except the text you ask to translate.
