# Phase 4 — Connecting the Android App

## What this phase is

The backend was live, but the app on the phone still had to be pointed at it. That means three
separate things must all agree:

1. The app must send API calls to **your** Cloud Run URL, not Omi's servers
2. The app must authenticate against **your** Firebase project, not Omi's
3. The app must be **signed** with a certificate registered in your Firebase project

Each one failed independently, producing three different errors on three different days. Almost
all of it traces back to a single script.

---

## The root cause of nearly everything: `setup.sh`

`app/setup.sh` is the repo's onboarding script. It installs dependencies, generates
localizations, and configures flavors — all genuinely useful. It also, silently, does this:

| Line | What it does | Effect on a fork |
|---|---|---|
| 52 | `API_BASE_URL=https://api.omiapi.com/` | Hardcodes **Omi's production API** |
| 80 | `cp setup/prebuilt/firebase_options.dart lib/firebase_options_dev.dart` | Overwrites Firebase config with Omi's |
| 81 | `cp setup/prebuilt/google-services.json android/app/src/dev/` | Same, for the native layer |
| 87–88 | same two copies, for the **prod** flavor | Same |
| 142 | `echo API_BASE_URL=$API_BASE_URL > .dev.env` | `>` **truncates** — your file is destroyed, not appended to |
| 143–144 | `USE_WEB_AUTH=true`, `USE_AUTH_CUSTOM_TOKEN=true` | Flips your auth flags |
| 159 | runs `build_runner` | **Bakes all of the above into compiled code** |
| — | writes `android/key.properties` | Points signing at Omi's shared debug keystore |

None of this is malicious. It's a script written for people working *on Omi*, where all those
values are correct. For a fork, it's a config bomb.

> ## ⚠️ Never run `app/setup.sh` on this repo again.
>
> It has already done its useful work (dependencies, l10n, flavors). Running it again reverts
> every fix in this document. If you need to re-install dependencies, run `flutter pub get`
> directly.

Worth noting what would have happened if the build had *succeeded* on the first attempt: you'd
have had a working app that talked to Omi's servers and never sent your backend a single
request, with nothing visibly wrong. **The build failure was lucky.**

---

## Understanding flavors first

Flutter/Android **flavors** let one codebase produce different apps. From
`app/android/app/build.gradle`:

| Flavor | applicationId | Firebase config source | Signing |
|---|---|---|---|
| `dev` | `com.friend.ios.dev` | `app/src/dev/google-services.json` | debug keystore |
| `prod` | `com.friend.ios` | `app/src/prod/google-services.json` | release keystore |

You are running **dev**. Everything below concerns the dev flavor; the prod flavor is still
entirely Omi's and is listed under [What's still broken](#whats-still-broken).

> **Which google-services.json actually wins.** Gradle's resolution order is
> `src/<flavor><BuildType>/` → `src/<buildType>/` → `src/<flavor>/` → `app/`. So for a dev build,
> `app/src/dev/google-services.json` beats the one at `app/google-services.json`. Editing the
> wrong file changes nothing.

---

## Bug 1 — A JRE where a JDK was needed

```
Toolchain installation '/usr/lib/jvm/java-17-openjdk-amd64' does not provide
the required capabilities: [JAVA_COMPILER]
```

> **JRE vs JDK.** A JRE (Runtime Environment) can *run* Java programs. A JDK (Development Kit)
> can also *compile* them — it includes `javac`. Gradle compiles Android code, so it needs a
> JDK.

The installed Java had `java` but no `javac`. `AGENTS.md` asks for JDK 21:

```bash
sudo apt install -y openjdk-21-jdk
ls /usr/lib/jvm/java-21-openjdk-amd64/bin/javac    # must exist
```

**Diagnostic value:** after this, the error changed from "no JAVA_COMPILER" to real compilation
errors. A *different* error is progress — it means the previous layer is now working.

---

## Bug 2 — Kotlin version conflict

Around 100 errors, all shaped like this:

```
error: cannot find symbol
public class WebSettingsCompatProxyApi extends PigeonApiWebSettingsCompat {
                                               ^
  symbol: class PigeonApiWebSettingsCompat
```

### Diagnosis

The plugin `webview_flutter_android 4.10.11` ships a Pigeon-generated **Kotlin** file
(`AndroidWebkitLibrary.g.kt`) that lives in `src/main/java/` alongside its Java files. About 30
Java classes extend base classes defined in that one Kotlin file.

The plugin's own `build.gradle` declares `ext.kotlin_version = '2.2.21'`. The app pinned
**2.1.0** in `app/android/settings.gradle`. Under the older toolchain the Kotlin file wasn't
compiled, so none of those base classes existed — and every Java file extending one failed at
once.

**~100 errors, one root cause.** When you see a wall of `cannot find symbol` all referencing
generated types, look for a version mismatch, not 100 separate problems.

A survey of the whole plugin cache showed 8 plugins wanting Kotlin newer than 2.1.0, up to
2.3.0. Webview was simply the first to break, because it's the one whose Java depends on Kotlin
generated *inside the same module*.

### Fix

`app/android/settings.gradle`, line 26:

```diff
- id "org.jetbrains.kotlin.android" version "2.1.0" apply false
+ id "org.jetbrains.kotlin.android" version "2.2.21" apply false
```

**This file is tracked in git** — it's the one deliberate source change from this phase. If
upstream later bumps Kotlin themselves, you'll get a one-line conflict and should take theirs.

If more plugins break later, 2.3.0 covers everything currently in the cache.

---

## Bug 3 — The app was authenticating against Omi's Firebase project

Symptom: the Google account picker opened fine, you chose an account, then **"Failed to sign
in"**.

> **Why the picker always works.** Choosing an account is pure Android — it doesn't involve your
> app's credentials at all. The failure comes immediately *after*, when Google checks whether
> your app is allowed to use the requested OAuth client. So "picker works, sign-in fails" always
> points at configuration, never at the picker.

### Two files, both wrong, and one overrides the other

| File | Pointed at | Should be |
|---|---|---|
| `app/android/app/src/dev/google-services.json` | `based-hardware-dev` | `void-ai-489016` |
| `app/lib/firebase_options_dev.dart` (android block) | `based-hardware-dev` | `void-ai-489016` |

**The Dart file matters more.** `app/lib/main.dart:143` calls:

```dart
await Firebase.initializeApp(options: options);   // options = firebase_options_dev.dart
```

Passing explicit `options` **overrides `google-services.json` entirely** for the Dart/plugin
layer. Fixing only the JSON would have left you exactly where you started. This is a genuinely
easy trap — the JSON is the file everyone thinks of.

The JSON still matters for the *native* layer: `auth_service.dart:152` calls
`GoogleSignIn(scopes: ['profile','email'])` with no `serverClientId`, so on Android it reads
`default_web_client_id`, a string resource generated from `google-services.json`.

### Fix

Download the correct config from your own Firebase project:

```bash
firebase apps:list --project void-ai-489016
firebase apps:sdkconfig ANDROID 1:684741928652:android:c716a47ea603d12dd80469 \
  --project void-ai-489016 > app/android/app/src/dev/google-services.json
```

And edit the android block of `app/lib/firebase_options_dev.dart`:

```dart
static const FirebaseOptions android = FirebaseOptions(
  apiKey: 'AIzaSyC0yD84WwQfSbAcmERBnXCzY5-LatOt_18',
  appId: '1:684741928652:android:8071c6e1db2649fad80469',
  messagingSenderId: '684741928652',
  projectId: 'void-ai-489016',
  storageBucket: 'void-ai-489016.firebasestorage.app',
);
```

> **Both files are gitignored** (`.gitignore:56` and `.gitignore:170`), so these changes produce
> no git diff. That's convenient but dangerous — nothing records that they were changed. This
> document is the record.

---

## Bug 4 — The generated env trap

After fixing Firebase, the error changed to **"Authentication failed"** — a *different* message,
from the `catch` block at `auth_provider.dart:165` rather than the null-credential branch. The
logcat stack frame pointed at line 150:

```dart
if (PlatformService.isMobile && !useWebAuth) {
  credential = await AuthService.instance.signInWithGoogleMobile();   // line 148 — expected
} else {
  credential = await AuthService.instance.authenticateWithProvider(   // line 150 — actual
    'google',
  );
}
```

Line 150 is the **web** auth branch. On an Android phone. So `Env.useWebAuth` was `true` —
despite `.dev.env` clearly saying `USE_WEB_AUTH=false`.

### Why the config file was lying

The app does not read `.dev.env` at runtime. The `envied` package reads it **at build time** and
generates `app/lib/env/dev_env.g.dart` with the values compiled in (obfuscated with XOR for the
string values).

`setup.sh` had run `build_runner` *while `.dev.env` contained Omi's values*. Restoring `.dev.env`
afterwards fixed the source but not the generated file. The generated file still held:

```dart
static const bool? useWebAuth = true;
static const bool? useAuthCustomToken = true;
// apiBaseUrl (XOR-obfuscated) decoded to: https://api.omiapi.com/
```

**The APK on the phone was talking to Omi's production API**, using the web auth flow, this
whole time.

### Why regenerating didn't work either

```bash
dart run build_runner build --delete-conflicting-outputs
# Built with build_runner in 33s; wrote 0 outputs.       ← nothing changed
```

`.dev.env` is not declared as a build **input**, so build_runner's cache never invalidated.
Deleting the generated file wasn't enough either — it restored it from cache (`2 same`).

### The fix that actually works

```bash
cd ~/Desktop/Void-AI/app
dart run build_runner clean
dart run build_runner build --delete-conflicting-outputs
```

> ## Remember this
> **Editing `.dev.env` changes nothing until you run `build_runner clean` *and* rebuild.**
> A plain rebuild will report success and change nothing at all.

Verify the result rather than trusting it:

```bash
grep -nE "useWebAuth|useAuthCustomToken" lib/env/dev_env.g.dart
# useWebAuth = false
# useAuthCustomToken = false
```

The API URL is obfuscated, so decode it:

```bash
python3 - <<'EOF'
import re
src = open('lib/env/dev_env.g.dart').read()
key  = [int(x) for x in re.findall(r'-?\d+', re.search(r'_enviedkeyapiBaseUrl\s*=\s*<int>\[(.*?)\]', src, re.S).group(1))]
data = [int(x) for x in re.findall(r'-?\d+', re.search(r'_envieddataapiBaseUrl\s*=\s*<int>\[(.*?)\]', src, re.S).group(1))]
print('BAKED apiBaseUrl =', ''.join(chr(d ^ k) for d,k in zip(data,key)))
EOF
```

---

## Bug 5 — Signed with the wrong certificate

Next error, from logcat:

```
OAuth Google sign in error: PlatformException(sign_in_failed,
  com.google.android.gms.common.api.ApiException: 10: , null, null)
```

> **`ApiException: 10` means `DEVELOPER_ERROR`.** It has exactly one cause: the certificate that
> signed the running app is not registered for the OAuth client it's trying to use. Not a
> network problem, not a token problem — a signing problem.

### The mismatch

| | SHA-1 |
|---|---|
| Registered in `void-ai-489016` for `com.friend.ios.dev` | `2DBB912D…5101` — your `~/.android/debug.keystore` |
| Actually signed the APK | `50F87A68…3598` — **Omi's** `setup/prebuilt/debug.keystore` |

That second fingerprint is one of the three registered in `based-hardware-dev`. `setup.sh` had
written `app/android/key.properties`:

```properties
keyAlias=androiddebugkey
storeFile=../../setup/prebuilt/debug.keystore
```

And `app/android/app/build.gradle:117-122` applies it to the **debug** signing config:

```groovy
debug {
    if (keystorePropertiesFile.exists()) {
        storeFile file(keystoreProperties['storeFile'])
        ...
    }
}
```

So even a debug build got signed with Omi's key — a keystore whose **private key is public in
their repository**.

### Fix

```bash
mv app/android/key.properties /tmp/key.properties.bak    # gitignored; no diff either way
adb uninstall com.friend.ios.dev                          # REQUIRED — see below
cd app && flutter run --flavor dev
```

With `key.properties` gone, Gradle falls back to the default `~/.android/debug.keystore`, whose
SHA-1 is already registered.

> **Why the uninstall is mandatory.** Android refuses to update an app when the signing
> certificate changes — it's a core security guarantee. You'd get
> `INSTALL_FAILED_UPDATE_INCOMPATIBLE`. Uninstalling first also clears cached Firebase session
> tokens issued by the *old* project, which can make sign-in look broken even after the config
> is right.

### Getting your SHA-1

```bash
keytool -list -v -keystore ~/.android/debug.keystore \
  -alias androiddebugkey -storepass android -keypass android | grep SHA1
```

### Getting the real error instead of the friendly one

```bash
adb logcat -c && adb logcat | grep -iE "OAuth Google sign in error|ApiException|PlatformException"
```

The app shows "Authentication failed"; the actual exception is logged at
`auth_provider.dart:163`. **Always get the logcat message** — the UI text is the same for
several completely different causes.

---

## The error progression, and why it mattered

Each fix produced a *new* error, and the sequence was the main diagnostic signal:

| Error | Meant |
|---|---|
| `no JAVA_COMPILER` | toolchain broken |
| `cannot find symbol: PigeonApi…` | toolchain fine, Kotlin version wrong |
| "Failed to sign in with Google" | build fine, wrong Firebase project + web auth path |
| "Authentication failed" / `ApiException: 10` | right project, right path, wrong signing cert |
| *(sign-in works)* | — |

**A new error is progress.** The same error repeating means your fix didn't take effect — which
is precisely what the build_runner cache was doing.

---

## Running the app

```bash
cd ~/Desktop/Void-AI/app
flutter run --flavor dev
```

No `setup.sh`. Gradle picks up `google-services.json` changes automatically (it's a tracked
build input), so no `flutter clean` is needed for those.

Checking the device:
```bash
adb devices     # must say "device", not "unauthorized"
```
"unauthorized" means the phone is waiting for you to tap **Allow USB debugging** on its screen.

---

## What's still broken

Not fixed, because they don't affect the dev build — but they will block distribution:

**The prod flavor is entirely Omi's.** Both `app/src/prod/google-services.json` and
`lib/firebase_options_prod.dart` point at `based-hardware-dev`. A release build today would fail
sign-in exactly as the dev build did.

**There is no release keystore.** `key.properties` also fed the *release* signing config
(`build.gradle:110-116`). With it moved aside, a release build has no signing key at all. You
need to generate your own, register its SHA-1 in Firebase, and never restore the old file — it
points at a keystore whose private key is publicly available.

**The iOS and web blocks** in `firebase_options_dev.dart` still reference `based-hardware-dev`.
Irrelevant on Android, relevant the day you build for iOS.
