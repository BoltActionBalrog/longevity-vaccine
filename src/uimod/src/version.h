#ifndef UIMOD_VERSION_H
#define UIMOD_VERSION_H

// Single source of truth for the Longevity Vaccine product version on the C++ side.
//
// Kept in lockstep with work\scripts\version.py -- work\tests\test_version_sync.py fails if the
// two disagree, so bump BOTH in the same commit.
//
// RC-SAFE: everything outside the RC_INVOKED guard is plain #define, so uimod.rc includes this
// file directly and the VERSIONINFO resource can never drift from the string the DLL logs.

#define UIMOD_VERSION_MAJOR 1
#define UIMOD_VERSION_MINOR 0
#define UIMOD_VERSION_PATCH 1
#define UIMOD_VERSION_STRING "1.0.1"

// The Thinker Mod build every thinker.dll detour is pinned to (PE TimeDateStamp + SizeOfImage), and the version
// the warning dialog / installer name. Mirrors work\scripts\version.py THINKER_SUPPORTED_*; test_version_sync pins it.
#define UIMOD_THINKER_SUPPORTED_VERSION "5.5"
#define UIMOD_THINKER_SUPPORTED_STAMP 0x6A821052
#define UIMOD_THINKER_SUPPORTED_IMAGE_SIZE 0x19F000
// Where a player gets that build: its tag on Thinker's GitHub releases (the page is update_core.h
// kThinkerReleasePagePrefix + this tag). UIMOD_THINKER_DEV_PAGE is empty for a GitHub release; when the pin is one of
// the author's development builds it holds that ONE build's own page and is used instead (user 2026-11-14).
#define UIMOD_THINKER_SUPPORTED_TAG "v5.5"
#define UIMOD_THINKER_DEV_PAGE ""

#ifndef RC_INVOKED
// Convenience alias for C++ callers -- NOT a second source of truth; it is defined from the macro
// above. Narrow `char` is deliberate even though the project builds with UNICODE: the only
// consumer is UimodLog(const char*), and the update checker (plan Phase 8) reports this string.
constexpr char kUimodVersion[] = UIMOD_VERSION_STRING;
#endif

#endif  // UIMOD_VERSION_H
