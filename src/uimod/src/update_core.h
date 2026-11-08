// uimod update checker -- the pure logic, header-only so work\tests\update_core_selftest.cpp can
// compile it without windows.h: the `install.py --check` pipe parser, the DeclinedUpdates
// read-merge-write, byte formatting, command-line building, the popup label-file builder and
// every player-facing string. update.cpp is the Win32 shell around this file. The flows are
// numbered F1..F8 throughout (F2 core update, F3 new pack, F6 manual install, F7/F8 hand-off
// failures); the installer's side of the contract is work\scripts\install.py `--check`.
//
// Rules of this file: no heap, no exceptions, no Windows headers, fixed buffers, every input
// treated as hostile (it crossed a pipe from a process that read the network).
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace lvupd {

// ---- the pipe contract (install.py "--check (the game's query)"; installer_exit.CHECK_*) ----
enum Code { kCodeNothing = 0, kCodeUpdates = 10, kCodeManual = 11, kCodeFailed = 12 };

// manifest.REASONS keys, 1:1 (kReasonUnspecified = the installer sent `manual=` with no key,
// kReasonOther = a key this DLL does not know: still a kill switch, shown with the generic text).
enum Reason { kReasonUnspecified = 0, kReasonProtocol, kReasonBootstrapDefect, kReasonBaseUnsupported,
              kReasonTooOld, kReasonOther };

constexpr int    kMaxItems = 4;          // stale[] / fresh[] each; the installer knows 2 packs
constexpr size_t kIniBuf   = 1024;       // receipt.py _INI_BUF: the profile API's read buffer
constexpr size_t kVerCap   = 18;         // "65535.65535.65535" is 17 chars -- version.py caps parts at 65535
constexpr size_t kIdCap    = 32;
constexpr size_t kLabelCap = 48;
constexpr unsigned long long kMaxSize = 1ull << 50;   // manifest.size_ok: 0 <= size < 2**50

// The ONLY URL the player ever sees. == manifest.DOWNLOAD_URL (pinned by test_update_core.py).
// Popups show it without the scheme (kDownloadUrlShown): shorter, and what a player types.
constexpr char kDownloadUrl[]      = "https://longevitymods.com/vaccine/download";
constexpr char kDownloadUrlShown[] = "longevitymods.com/vaccine/download";

// The packs this DLL knows, with THEIR player-facing names -- == install.MODULE_LABELS (pinned by
// test_update_core.py). The pipe carries a label too, but the DLL shows only its own: an item
// with an id it does not know is skipped (a newer installer than this DLL), never displayed.
struct KnownModule { const char* id; const char* label; };
constexpr KnownModule kKnownModules[] = {
    { "movies-hd",    "HD Cinematics" },
    { "portraits-hd", "Turovetsky's HD Portrait Pack" },
};
inline const char* KnownLabel(const char* id, size_t n)
{
    for (const KnownModule& m : kKnownModules)
        if (strlen(m.id) == n && memcmp(m.id, id, n) == 0) return m.label;
    return nullptr;
}

// ---- versions (version.py grammar: MAJOR.MINOR.PATCH, digits, no leading zeros, <= 65535) ----
struct Version { unsigned v[3]; };

inline bool ParseVersion(const char* s, size_t n, Version* out)
{
    unsigned parts[3] = { 0, 0, 0 };
    size_t i = 0;
    for (int p = 0; p < 3; ++p) {
        size_t digits = 0;
        unsigned val = 0;
        while (i < n && s[i] >= '0' && s[i] <= '9') {
            if (digits == 1 && val == 0) return false;         // leading zero
            if (++digits > 5) return false;
            val = val * 10 + static_cast<unsigned>(s[i] - '0');
            ++i;
        }
        if (digits == 0 || val > 65535) return false;
        parts[p] = val;
        if (p < 2) { if (i >= n || s[i] != '.') return false; ++i; }
    }
    if (i != n) return false;
    if (out) { out->v[0] = parts[0]; out->v[1] = parts[1]; out->v[2] = parts[2]; }
    return true;
}

inline int CompareVersion(const Version& a, const Version& b)
{
    for (int i = 0; i < 3; ++i) {
        if (a.v[i] < b.v[i]) return -1;
        if (a.v[i] > b.v[i]) return 1;
    }
    return 0;
}

inline int CompareVersionStr(const char* a, const char* b)     // both already validated
{
    Version va, vb;
    ParseVersion(a, strlen(a), &va);
    ParseVersion(b, strlen(b), &vb);
    return CompareVersion(va, vb);
}

inline bool IsVersionStr(const char* s) { return ParseVersion(s, strlen(s), nullptr); }

// Printable ASCII (install._LINE_OK): what a whole `value` may hold ('|' separates its fields).
inline bool LineCharsOk(const char* s, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x20 || c > 0x7E || c == '=') return false;
    }
    return true;
}

// One field: printable ASCII, none of the protocol's separators (install._pipe_field's complement).
inline bool FieldOk(const char* s, size_t n)
{
    if (!LineCharsOk(s, n)) return false;
    for (size_t i = 0; i < n; ++i) if (s[i] == '|') return false;
    return true;
}

inline bool CopyField(const char* s, size_t n, char* out, size_t cap)
{
    if (n >= cap) return false;
    memcpy(out, s, n);
    out[n] = 0;
    return true;
}

// ---- the parsed answer ----
struct Item {
    char id[kIdCap];
    char label[kLabelCap];
    char from[kVerCap];          // stale only; "" for a new pack
    char to[kVerCap];
    unsigned long long bytes;
    bool hasBytes;
};

struct UpdateInfo {
    int  code;                   // Code; kCodeFailed for anything the parser refused
    char latest[kVerCap];        // "" when absent (manual / failed / yanked)
    bool hasBase;
    char baseFrom[kVerCap];      // "0.0.0" = unknown
    char baseTo[kVerCap];
    Item stale[kMaxItems]; int nStale;
    int  nUnknownStale;          // stale= lines whose module id this DLL does not know (a newer installer's pack): never
                                 // named in a popup, so never handed off (--only-listed); Present() logs the count
    Item fresh[kMaxItems]; int nFresh;
    int  manualReason;           // Reason (meaningful when code == kCodeManual)
    char manualKey[24];          // the raw key, for the log
};

inline void ClearInfo(UpdateInfo* o) { memset(o, 0, sizeof *o); o->code = kCodeFailed; }

enum ParseStatus {
    kOk = 0, kBadExit, kOverflow, kNoLf, kMalformed, kUnknownKey, kBadOrder, kDuplicate,
    kTooManyItems, kBadField, kBadVersion, kCodeMismatch
};

inline const char* ParseStatusName(int s)
{
    static const char* const names[] = { "ok", "bad-exit-code", "overflow", "no-final-lf", "malformed-line",
                                         "unknown-key", "bad-order", "duplicate-key", "too-many-items",
                                         "bad-field", "bad-version", "exit-code-mismatch" };
    return s >= 0 && s < static_cast<int>(sizeof names / sizeof *names) ? names[s] : "?";
}

inline Reason ReasonFromKey(const char* k, size_t n)
{
    if (n == 0) return kReasonUnspecified;
    if (n == 8  && memcmp(k, "protocol", 8) == 0) return kReasonProtocol;
    if (n == 16 && memcmp(k, "bootstrap_defect", 16) == 0) return kReasonBootstrapDefect;
    if (n == 16 && memcmp(k, "base_unsupported", 16) == 0) return kReasonBaseUnsupported;
    if (n == 7  && memcmp(k, "too_old", 7) == 0) return kReasonTooOld;
    return kReasonOther;
}

namespace detail {

// `<have>><offered>` -> two versions, have < offered (an "update" never goes backwards).
inline bool ParseRange(const char* s, size_t n, char* from, char* to)
{
    const char* gt = static_cast<const char*>(memchr(s, '>', n));
    if (!gt) return false;
    const size_t a = static_cast<size_t>(gt - s), b = n - a - 1;
    Version va, vb;
    if (!ParseVersion(s, a, &va) || !ParseVersion(gt + 1, b, &vb) || CompareVersion(va, vb) >= 0) return false;
    return CopyField(s, a, from, kVerCap) && CopyField(gt + 1, b, to, kVerCap);
}

inline bool ParseBytes(const char* s, size_t n, Item* it)
{
    it->bytes = 0; it->hasBytes = false;
    if (n == 0) return true;
    if (n > 16 || (n > 1 && s[0] == '0')) return false;   // 2**50 has 16 digits; no leading zeros
    unsigned long long v = 0;
    for (size_t i = 0; i < n; ++i) {
        if (s[i] < '0' || s[i] > '9') return false;
        v = v * 10 + static_cast<unsigned long long>(s[i] - '0');
    }
    if (v >= kMaxSize) return false;                       // install._pipe_size / manifest.size_ok
    it->bytes = v; it->hasBytes = true;
    return true;
}

// Split `s` on '|' into at most `want` fields; false unless exactly `want`.
inline bool SplitBar(const char* s, size_t n, int want, const char** f, size_t* fl)
{
    int k = 0;
    size_t start = 0;
    for (size_t i = 0; i <= n; ++i) {
        if (i == n || s[i] == '|') {
            if (k >= want) return false;
            f[k] = s + start; fl[k] = i - start; ++k;
            start = i + 1;
        }
    }
    return k == want;
}

enum ItemVerdict { kItemOk, kItemBad, kItemUnknownId };

// One `stale=` / `new=` value. The pipe's label is validated but NOT kept: the item shows this
// DLL's compiled-in name for the id. An id this DLL does not know is a newer installer's pack:
// skipped (kItemUnknownId), so the rest of the answer still counts.
inline ItemVerdict ParseItem(const char* s, size_t n, bool stale, Item* it)
{
    const char* f[4]; size_t fl[4];
    if (!SplitBar(s, n, 4, f, fl)) return kItemBad;
    if (fl[0] == 0 || fl[0] >= kIdCap || fl[1] == 0 || fl[1] >= kLabelCap || !FieldOk(f[1], fl[1])) return kItemBad;
    for (size_t i = 0; i < fl[0]; ++i) {            // ids are compiled-in slugs: [a-z0-9-]
        const char c = f[0][i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return kItemBad;
    }
    if (stale) { if (!ParseRange(f[2], fl[2], it->from, it->to)) return kItemBad; }
    else {
        it->from[0] = 0;
        if (!ParseVersion(f[2], fl[2], nullptr) || !CopyField(f[2], fl[2], it->to, kVerCap)) return kItemBad;
    }
    if (!ParseBytes(f[3], fl[3], it)) return kItemBad;
    const char* label = KnownLabel(f[0], fl[0]);
    if (!label) return kItemUnknownId;
    CopyField(f[0], fl[0], it->id, kIdCap);
    strcpy(it->label, label);
    return kItemOk;
}

inline bool SeenId(const UpdateInfo& o, const char* id, size_t n)
{
    for (int i = 0; i < o.nStale; ++i) if (strlen(o.stale[i].id) == n && memcmp(o.stale[i].id, id, n) == 0) return true;
    for (int i = 0; i < o.nFresh; ++i) if (strlen(o.fresh[i].id) == n && memcmp(o.fresh[i].id, id, n) == 0) return true;
    return false;
}

inline size_t IdLen(const char* val, size_t vl)
{
    const char* bar = static_cast<const char*>(memchr(val, '|', vl));
    return bar ? static_cast<size_t>(bar - val) : vl;
}

} // namespace detail

// The strict parser. `exitCode` is the child's exit code (or kCodeFailed when it was killed);
// `overflow` says the 64 KB cap was hit. On any failure *out is a kCodeFailed answer and
// *badLine (1-based) names the line. Rules (test_check.py's truth table, read the other way):
//   * exit in {0, 10, 11, 12}; 12 -> nothing is parsed (the installer printed nothing).
//   * every line `key=value`, LF-terminated, printable ASCII, keys in the fixed order
//     latest, base, stale*, new*; `manual` alone. Each of latest/base at most once.
//   * exit 0: only `latest` (or nothing: yanked). exit 10: latest + >= 1 item. exit 11: manual only.
namespace detail {
inline ParseStatus ParseCheckOutputInto(const char* buf, size_t len, int exitCode, UpdateInfo& o, int* badLine)
{
    if (len > 0 && buf[len - 1] != '\n') return kNoLf;
    int stage = -1;                                 // -1 none, 0 latest, 1 base, 2 stale, 3 new, 9 manual
    int lineNo = 0, items = 0;                      // items counts skipped (unknown-id) ones too
    for (size_t pos = 0; pos < len; ) {
        const char* line = buf + pos;
        const char* nl = static_cast<const char*>(memchr(line, '\n', len - pos));
        const size_t ll = static_cast<size_t>(nl - line);
        pos += ll + 1;
        ++lineNo;
        if (badLine) *badLine = lineNo;
        if (ll == 0) return kMalformed;
        const char* eq = static_cast<const char*>(memchr(line, '=', ll));
        if (!eq) return kMalformed;
        const size_t kl = static_cast<size_t>(eq - line);
        const char* val = eq + 1;
        const size_t vl = ll - kl - 1;
        if (!LineCharsOk(val, vl)) return kBadField;
        for (size_t i = 0; i < kl; ++i) if (line[i] < 'a' || line[i] > 'z') return kMalformed;

        if (kl == 6 && memcmp(line, "latest", 6) == 0) {
            if (stage != -1) return stage == 0 ? kDuplicate : kBadOrder;
            if (!FieldOk(val, vl) || !ParseVersion(val, vl, nullptr) || !CopyField(val, vl, o.latest, kVerCap)) return kBadVersion;
            stage = 0;
        } else if (kl == 4 && memcmp(line, "base", 4) == 0) {
            if (stage == 1) return kDuplicate;
            if (stage != 0) return kBadOrder;
            if (!detail::ParseRange(val, vl, o.baseFrom, o.baseTo)) return kBadVersion;
            if (strcmp(o.baseTo, o.latest) != 0) return kBadVersion;   // the core is offered AT latest
            o.hasBase = true; stage = 1; ++items;
        } else if (kl == 5 && memcmp(line, "stale", 5) == 0) {
            if (stage < 0 || stage > 2) return kBadOrder;
            if (o.nStale >= kMaxItems) return kTooManyItems;
            if (SeenId(o, val, IdLen(val, vl))) return kDuplicate;
            const ItemVerdict v = detail::ParseItem(val, vl, true, &o.stale[o.nStale]);
            if (v == kItemBad) return kBadField;
            if (v == kItemOk) ++o.nStale; else ++o.nUnknownStale;
            stage = 2; ++items;
        } else if (kl == 3 && memcmp(line, "new", 3) == 0) {
            if (stage < 0 || stage > 3) return kBadOrder;
            if (o.nFresh >= kMaxItems) return kTooManyItems;
            if (SeenId(o, val, IdLen(val, vl))) return kDuplicate;
            const ItemVerdict v = detail::ParseItem(val, vl, false, &o.fresh[o.nFresh]);
            if (v == kItemBad) return kBadField;
            if (v == kItemOk) ++o.nFresh;
            stage = 3; ++items;
        } else if (kl == 6 && memcmp(line, "manual", 6) == 0) {
            if (stage != -1) return kBadOrder;
            for (size_t i = 0; i < vl; ++i)
                if (!((val[i] >= 'a' && val[i] <= 'z') || val[i] == '_')) return kBadField;
            if (!CopyField(val, vl, o.manualKey, sizeof o.manualKey)) return kBadField;
            o.manualReason = ReasonFromKey(val, vl);
            stage = 9;
        } else {
            return kUnknownKey;
        }
    }
    if (badLine) *badLine = 0;

    // exit code vs content
    if (exitCode == kCodeManual) { if (stage != 9) return kCodeMismatch; }
    else if (stage == 9) return kCodeMismatch;
    else if (exitCode == kCodeNothing) { if (items != 0) return kCodeMismatch; }
    else /* kCodeUpdates */ { if (stage < 0 || items == 0) return kCodeMismatch; }
    o.code = exitCode;
    return kOk;
}
} // namespace detail

inline ParseStatus ParseCheckOutput(const char* buf, size_t len, int exitCode, bool overflow,
                                    UpdateInfo* out, int* badLine)
{
    ClearInfo(out);
    if (badLine) *badLine = 0;
    if (exitCode != kCodeNothing && exitCode != kCodeUpdates && exitCode != kCodeManual && exitCode != kCodeFailed)
        return kBadExit;
    if (overflow) return kOverflow;
    if (exitCode == kCodeFailed) return kOk;        // could not check; whatever was printed is noise
    UpdateInfo tmp;
    ClearInfo(&tmp);
    const ParseStatus st = detail::ParseCheckOutputInto(buf, len, exitCode, tmp, badLine);
    if (st == kOk) *out = tmp;                      // a refused answer leaves NO items behind
    return st;
}

// ---- byte formatting: what the prompt shows for a pack's download size ----
// Binary units, GB/MB labels ("1.3 GB", "640 MB", "12 KB"); "" when the size is unknown.
inline size_t FormatBytes(unsigned long long b, bool known, char* out, size_t cap)
{
    if (!known || cap < 12) { if (cap) out[0] = 0; return 0; }
    char tmp[24]; size_t n = 0;
    auto putu = [&](unsigned long long v) {
        char d[24]; size_t k = 0;
        do { d[k++] = static_cast<char>('0' + v % 10); v /= 10; } while (v);
        while (k) tmp[n++] = d[--k];
    };
    // Pick the unit by the ROUNDED value, so 1048575 is "1 MB", not "1024 KB".
    const unsigned long long mb = (b + (1ull << 19)) >> 20, kb = (b + (1ull << 9)) >> 10;
    if (b >= (1ull << 30) || mb >= 1024) {
        const unsigned long long tenths = (b * 10 + (1ull << 29)) >> 30;     // round to 0.1 GB
        putu(tenths / 10); tmp[n++] = '.'; tmp[n++] = static_cast<char>('0' + tenths % 10);
        memcpy(tmp + n, " GB", 3); n += 3;
    } else if (b >= (1ull << 20) || kb >= 1024) {
        putu(mb); memcpy(tmp + n, " MB", 3); n += 3;
    } else if (b >= (1ull << 10)) {
        putu(kb); memcpy(tmp + n, " KB", 3); n += 3;
    } else {
        putu(b); memcpy(tmp + n, " bytes", 6); n += 6;
    }
    if (n >= cap) n = cap - 1;
    memcpy(out, tmp, n); out[n] = 0;
    return n;
}

// ---- [Longevity] DeclinedUpdates (receipt.py: declined() / decline() / clear_declines()) ----
// `item:ver;item:ver;...`, sorted by item on write; the version is everything after the LAST ':'
// (so `new:<id>` keeps its colon); "*" = declined at every version ("Don't ask me again" on a NEW
// pack's offer, "Don't show this again" on the manual notice); an update offer is declined at
// its offered version only (DeclineVersionFor).
constexpr char kDeclineAny[] = "*";
constexpr int  kMaxDeclines = 64;      // > 1023 / len("a:1.0.0;") = 128 is impossible with real ids; 64 is ample

struct Declines {
    struct E { char item[64]; char ver[kVerCap]; } e[kMaxDeclines];
    int  n;
    bool overflow;                     // more entries than fit: NEVER rewrite (we would erase some)
};

// The DeclinedUpdates item for the manual-install notice with `reasonKey` ("" = unspecified)
// -- receipt.manual_decline_item.
inline bool ManualDeclineItem(const char* reasonKey, char* out, size_t cap)
{
    const char* r = reasonKey && reasonKey[0] ? reasonKey : "unspecified";
    if (strlen(r) + 8 >= cap) return false;
    memcpy(out, "manual-", 7);
    strcpy(out + 7, r);
    return true;
}

inline bool DeclineItemOk(const char* item, size_t n)
{
    if (n == 0 || n >= 64) return false;
    for (size_t i = 0; i < n; ++i) {
        const unsigned char c = static_cast<unsigned char>(item[i]);
        if (c <= 0x20 || c >= 0x7F) return false;              // receipt: 32 < ord < 127
        if (c == ';' || c == '=' || c == '[' || c == ']') return false;
    }
    return true;
}

inline bool DeclineVerOk(const char* v, size_t n)
{
    return (n == 1 && v[0] == '*') || ParseVersion(v, n, nullptr);
}

namespace detail {
inline void Trim(const char*& s, size_t& n)
{
    while (n && (s[0] == ' ' || s[0] == '\t' || s[0] == '\r' || s[0] == '\n')) { ++s; --n; }
    while (n && (s[n - 1] == ' ' || s[n - 1] == '\t' || s[n - 1] == '\r' || s[n - 1] == '\n')) --n;
}
inline int Find(const Declines& d, const char* item, size_t n)
{
    for (int i = 0; i < d.n; ++i)
        if (strlen(d.e[i].item) == n && memcmp(d.e[i].item, item, n) == 0) return i;
    return -1;
}
inline bool Put(Declines* d, const char* item, size_t in, const char* ver, size_t vn)
{
    int i = Find(*d, item, in);
    if (i < 0) { if (d->n >= kMaxDeclines) { d->overflow = true; return false; } i = d->n++; }
    memcpy(d->e[i].item, item, in); d->e[i].item[in] = 0;
    memcpy(d->e[i].ver, ver, vn);   d->e[i].ver[vn] = 0;
    return true;
}
} // namespace detail

// receipt.declined(): tolerant. Malformed entries are dropped; a value the profile API truncated
// (rawLen >= kIniBuf - 1) loses its last entry; a later duplicate wins.
inline void DeclineParse(const char* raw, size_t rawLen, Declines* out)
{
    out->n = 0;
    out->overflow = false;
    size_t start = 0;
    const bool truncated = rawLen >= kIniBuf - 1;
    for (size_t i = 0; i <= rawLen; ++i) {
        if (i < rawLen && raw[i] != ';') continue;
        const char* part = raw + start; size_t pn = i - start;
        start = i + 1;
        if (truncated && i == rawLen) break;                    // drop the last (possibly cut) entry
        detail::Trim(part, pn);
        size_t colon = pn;
        while (colon > 0 && part[colon - 1] != ':') --colon;    // rpartition(':')
        if (colon == 0) continue;
        const char* item = part; size_t in = colon - 1;
        const char* ver = part + colon; size_t vn = pn - colon;
        detail::Trim(item, in); detail::Trim(ver, vn);
        if (in == 0 || in >= 64 || vn >= kVerCap || !DeclineVerOk(ver, vn)) continue;
        detail::Put(out, item, in, ver, vn);
    }
}

// receipt.decline(): refuse what declined() could not read back; replace or add.
inline bool DeclineSet(Declines* d, const char* item, const char* ver)
{
    const size_t in = strlen(item), vn = strlen(ver);
    if (!DeclineItemOk(item, in) || !DeclineVerOk(ver, vn) || vn >= kVerCap) return false;
    return detail::Put(d, item, in, ver, vn);
}

// `sorted(d.items())` joined by ';'. False if the value would not fit the profile buffer (the
// readers treat >= 1023 chars as truncated) or if the parse overflowed (a rewrite would erase
// entries this reader could not hold).
inline bool DeclineFormat(const Declines& d, char* out, size_t cap)
{
    if (d.overflow) return false;
    int order[kMaxDeclines];
    for (int i = 0; i < d.n; ++i) order[i] = i;
    for (int i = 1; i < d.n; ++i) {                             // insertion sort by strcmp (== Python's on ASCII)
        const int k = order[i]; int j = i - 1;
        while (j >= 0 && strcmp(d.e[order[j]].item, d.e[k].item) > 0) { order[j + 1] = order[j]; --j; }
        order[j + 1] = k;
    }
    size_t o = 0;
    for (int i = 0; i < d.n; ++i) {
        const char* it = d.e[order[i]].item; const char* v = d.e[order[i]].ver;
        const size_t need = strlen(it) + 1 + strlen(v) + (i ? 1 : 0);
        if (o + need >= cap || o + need >= kIniBuf - 1) return false;
        if (i) out[o++] = ';';
        memcpy(out + o, it, strlen(it)); o += strlen(it);
        out[o++] = ':';
        memcpy(out + o, v, strlen(v)); o += strlen(v);
    }
    out[o] = 0;
    return true;
}

// ---- the game's command line: tester switches `--lv-manifest=<path-or-URL>` / `--lv-delay=<s>` ----
// Tokens split on whitespace outside double quotes; quotes are stripped; the LAST occurrence
// wins; a value with an embedded quote is refused (it could not be re-quoted safely).
inline bool ExtractSwitchValue(const wchar_t* cmd, const wchar_t* kSwitch, wchar_t* out, size_t cap)
{
    const size_t sw = wcslen(kSwitch);
    bool found = false;
    wchar_t tok[2048];
    size_t tn = 0; bool inq = false, bad = false;
    for (size_t i = 0; ; ++i) {
        const wchar_t c = cmd[i];
        const bool end = c == 0 || (!inq && (c == L' ' || c == L'\t'));
        if (!end) {
            if (c == L'"') {
                // An OPENING quote may wrap the whole token (tn == 0) or just the value (tn == sw);
                // one anywhere else is a quote INSIDE the value -> refused.
                if (!inq && tn != 0 && tn != sw) bad = true;
                inq = !inq;
            } else if (tn < 2047) tok[tn++] = c;
            else bad = true;                                            // too long: refused, never cut
            continue;
        }
        tok[tn] = 0;
        if (tn > sw && wcsncmp(tok, kSwitch, sw) == 0 && !bad) {
            const size_t vn = tn - sw;
            if (vn < cap) { memcpy(out, tok + sw, (vn + 1) * sizeof(wchar_t)); found = true; }
        }
        tn = 0; bad = false;
        if (c == 0) break;
    }
    return found;
}

inline bool ExtractLvManifest(const wchar_t* cmd, wchar_t* out, size_t cap)
{
    return ExtractSwitchValue(cmd, L"--lv-manifest=", out, cap);
}

// `--lv-delay=<seconds>`: hold the check back so its answer lands mid-game (to exercise the
// turn-start prompt). 0 when absent or not a plain number; capped at 10 minutes.
inline int ExtractLvDelaySeconds(const wchar_t* cmd)
{
    wchar_t v[16];
    if (!ExtractSwitchValue(cmd, L"--lv-delay=", v, 16) || !v[0]) return 0;
    int n = 0;
    for (const wchar_t* p = v; *p; ++p) {
        if (*p < L'0' || *p > L'9') return 0;
        n = n * 10 + static_cast<int>(*p - L'0');
        if (n > 600) return 600;
    }
    return n;
}

// The game directory from the exe's full path: everything before the last backslash -- except a
// drive root, which keeps it (`D:\`; `D:` alone means the CURRENT directory of drive D), also
// behind a `\\?\` or `\\.\` prefix (`\\?\C:` names the volume device, not its root). False when
// there is no backslash or the result does not fit.
inline bool GameDirFromExePath(const wchar_t* exe, wchar_t* out, size_t cap)
{
    const wchar_t* slash = wcsrchr(exe, L'\\');
    if (!slash) return false;
    const bool device = exe[0] == L'\\' && exe[1] == L'\\' && (exe[2] == L'?' || exe[2] == L'.') && exe[3] == L'\\';
    const wchar_t* drive = device ? exe + 4 : exe;          // "X:" of a drive path, prefix or not
    const bool root = drive[0] && drive[1] == L':' && slash == drive + 2;
    const size_t n = static_cast<size_t>(slash - exe) + (root ? 1 : 0);
    if (n + 1 > cap) return false;
    memcpy(out, exe, n * sizeof(wchar_t));
    out[n] = 0;
    return true;
}

// Appends `"<s>"` at out[o] so the MSVC CRT argv parser -- CommandLineToArgvW, and Python's own
// argv -- reads back EXACTLY `s`. Backslashes are literal there except in a run that ends at a
// quote, so the run before the CLOSING quote is doubled: `"D:\"` read back as `D:"` plus the rest
// of the line (a game at a drive root lost --wait-pid, --only-listed and --modules, 2026-11-01).
// A path without a trailing backslash comes out exactly as before. `s` must hold no quote (the
// callers refuse one). Leaves room for the terminator; false when it does not fit.
inline bool AppendArgQuoted(wchar_t* out, size_t& o, size_t cap, const wchar_t* s)
{
    const size_t n = wcslen(s);
    size_t tail = 0;
    while (tail < n && s[n - 1 - tail] == L'\\') ++tail;
    if (o + n + tail + 2 >= cap) return false;
    out[o++] = L'"';
    memcpy(out + o, s, n * sizeof(wchar_t)); o += n;
    for (size_t i = 0; i < tail; ++i) out[o++] = L'\\';
    out[o++] = L'"';
    return true;
}

// `"<python>" "<script>" --check --game-dir "<game>" [--manifest "<manifest>"]`, each path quoted
// by AppendArgQuoted, so the receiver reads it back exactly -- a drive root `D:\` included. Refuses
// an empty argument, one with a quote, and one that is nothing but backslashes.
inline bool BuildCheckCommandLine(const wchar_t* python, const wchar_t* script, const wchar_t* game,
                                  const wchar_t* manifest, wchar_t* out, size_t cap)
{
    size_t o = 0;
    auto put = [&](const wchar_t* s, size_t n) {
        if (o + n >= cap) return false;
        memcpy(out + o, s, n * sizeof(wchar_t)); o += n; return true;
    };
    auto quoted = [&](const wchar_t* s) {
        if (!s || !s[0] || wcschr(s, L'"') || wcsspn(s, L"\\") == wcslen(s)) return false;
        return AppendArgQuoted(out, o, cap, s);
    };
    if (!quoted(python) || !put(L" ", 1) || !quoted(script) || !put(L" --check --game-dir ", 20) || !quoted(game))
        return false;
    if (manifest && manifest[0]) { if (!put(L" --manifest ", 12) || !quoted(manifest)) return false; }
    out[o] = 0;
    return true;
}

// A compiled-in module id as the hand-off may name it: 1..kIdCap-1 of [a-z0-9-].
inline bool HandoffIdOk(const char* id)
{
    if (!id || !id[0]) return false;
    size_t n = 0;
    for (; id[n]; ++n) {
        const char c = id[n];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
    }
    return n < kIdCap;
}

// The modules the hand-off names -- EXACTLY what the popups listed and the player accepted: every
// stale pack of the update popup when that update was accepted, then every new pack accepted in
// its own popup (user decision 2026-10-31: the game hands the updater the list, the updater installs
// the list). Returns the count, or -1 when `cap` is too small or an id is malformed: then nothing
// is spawned, because an install the popups did not name must never happen.
inline int HandoffModules(const UpdateInfo& u, bool updateAccepted, const char* const* acceptedNew, int nNew,
                          const char** out, int cap)
{
    int n = 0;
    if (updateAccepted)
        for (int i = 0; i < u.nStale; ++i) {
            if (n >= cap || !HandoffIdOk(u.stale[i].id)) return -1;
            out[n++] = u.stale[i].id;
        }
    for (int i = 0; i < nNew; ++i) {
        if (n >= cap || !HandoffIdOk(acceptedNew[i])) return -1;
        out[n++] = acceptedNew[i];
    }
    return n;
}

// The hand-off itself: `"<cmd.exe>" /D /S /C ""<bat>" --update --game-dir "<game>" --wait-pid <pid>
// --only-listed [--modules a,b] [--manifest "<manifest>"]"`. `--only-listed` tells the updater to
// fetch EXACTLY the packs named (none when --modules is absent) and never to add other stale
// installed packs; the core still comes along whenever it is stale -- the bootstrap runs the newest
// installer by nature, and the popup always lists the core when it is stale and undeclined. Refuses
// a path or manifest with a quote, a cmd.exe metacharacter or nothing but backslashes, and any id
// HandoffIdOk rejects. Paths
// are quoted by AppendArgQuoted: cmd.exe and the batch file's %* pass them through untouched, and
// the python that finally parses them reads back exactly what was given (a drive root included).
inline bool BuildUpdateCommandLine(const wchar_t* cmdExe, const wchar_t* bat, const wchar_t* game, unsigned long pid,
                                   const char* const* mods, int nMods, const wchar_t* manifest,
                                   wchar_t* out, size_t cap)
{
    size_t o = 0;
    auto put = [&](const wchar_t* s, size_t n) {
        if (o + n >= cap) return false;
        memcpy(out + o, s, n * sizeof(wchar_t)); o += n; return true;
    };
    auto clean = [](const wchar_t* s) {
        return s && s[0] && !wcspbrk(s, L"\"%!&|<>^\r\n") && wcsspn(s, L"\\") != wcslen(s);
    };
    auto quoted = [&](const wchar_t* s) { return clean(s) && AppendArgQuoted(out, o, cap, s); };
    if (!quoted(cmdExe) || !put(L" /D /S /C \"", 11) || !quoted(bat) || !put(L" --update --game-dir ", 21) || !quoted(game))
        return false;
    wchar_t num[24];                                      // the pid in decimal (no CRT formatting: this header is CRT-free)
    size_t nn = 0;
    do { num[nn++] = static_cast<wchar_t>(L'0' + pid % 10); pid /= 10; } while (pid && nn < 20);
    for (size_t a = 0, b = nn - 1; a < b; ++a, --b) { const wchar_t t = num[a]; num[a] = num[b]; num[b] = t; }
    if (!put(L" --wait-pid ", 12) || !put(num, nn) || !put(L" --only-listed", 14)) return false;
    if (nMods < 0) return false;
    for (int i = 0; i < nMods; ++i) {
        if (!HandoffIdOk(mods[i])) return false;
        if (!put(i == 0 ? L" --modules " : L",", i == 0 ? 11 : 1)) return false;
        wchar_t w[kIdCap];
        size_t k = 0;
        for (; mods[i][k]; ++k) w[k] = static_cast<wchar_t>(mods[i][k]);
        if (!put(w, k)) return false;
    }
    if (manifest && manifest[0]) { if (!put(L" --manifest ", 12) || !quoted(manifest)) return false; }
    if (!put(L"\"", 1)) return false;
    out[o] = 0;
    return true;
}

// The resident updater's interpreter for this Windows, relative to the game directory. CPython 3.12
// (tools\python) does not start below Windows 8.1 (kernel 6.3) -- the loader kills it before a line
// of ours runs -- so the payload carries CPython 3.8 (tools\python38) for Windows 7 and 8.
// run-install.bat (`ver`) and bootstrap.py make the same choice. Pure: update.cpp feeds it
// RtlGetVersion's numbers (GetVersionEx / VerifyVersionInfo lie to an unmanifested exe on 10+).
inline const wchar_t* RuntimeExeRel(unsigned long major, unsigned long minor)
{
    const bool old = major < 6 || (major == 6 && minor < 3);
    return old ? L"LongevityMods\\updater\\tools\\python38\\python.exe"
               : L"LongevityMods\\updater\\tools\\python\\python.exe";
}

// ---- popup label file (script.txt grammar: #LABEL / #xs / #caption / #sprite / body / blank / replies) ----
// Text rules the engine imposes: `^` = line break, `$ { } [ ]` are markup, consecutive body lines
// are JOINED with a space (script.txt wraps its paragraphs at ~80 columns and relies on that).
// The engine's line reader has a FIXED stack buffer sized for such lines: a 330-character body
// on one physical line overwrote a return address with our own text (crash at the main menu,
// 2026-09-27, fault EIP 0x6f662066 = "f fo" from "off for good"). So the body is emitted as
// physical lines of at most kMaxPhysLine characters, broken at spaces, '\n' -> '^', and every
// other markup byte (and anything non-ASCII) becomes a space. Replies are single short lines.
constexpr size_t kMaxPhysLine = 96;      // vanilla's longest script.txt line is 106; conceptsx 174
struct LabelSpec {
    const char* label;       // "UPDATE"
    const char* caption;     // "Longevity Mod"
    int         xs;          // box width on the 800x600 baseline (REALLYQUIT: 320)
    const char* sprite;      // "longevity_sm.pcx" or nullptr (text-only popup)
    const char* body;        // '\n'-separated
    const char* replies[5];
    int         nReplies;    // 1..5 (0 = the engine shows its own OK)
};

namespace detail {
// Emits sanitised text. A leading '#' (directive / new label) or ';' (comment) on any physical
// line would change what the engine reads the line as, so it becomes a space. With `wrap`
// (the body): a '\n' becomes a new physical line that STARTS with '^' -- the engine's line
// break (script.txt rule 7: "Lines beginning with ^ begin on new lines"; a lone '^' line is a
// blank line; an inline '^' is just a character, seen in-game 2026-09-27) -- and a space is
// turned into a plain physical line break whenever the current physical line has reached
// kMaxPhysLine (the engine re-joins those with a space); a single word longer than that is
// broken hard rather than overflow the reader. Without `wrap` (replies, caption) a '\n' is a space.
inline bool PutSan(char* out, size_t cap, size_t& o, const char* s, bool body, bool wrap = false)
{
    bool lineStart = true;
    size_t col = 0;
    for (; *s; ++s) {
        unsigned char c = static_cast<unsigned char>(*s);
        if (c == '\n' && body && wrap) {
            if (o + 3 >= cap) return false;
            out[o++] = '\r'; out[o++] = '\n'; out[o++] = '^';
            col = 1; lineStart = false;
            continue;
        }
        if (c == '\n') c = ' ';
        else if (c == '\r') continue;
        else if (c == '$' || c == '{' || c == '}' || c == '[' || c == ']' || c == '^' || c < 0x20 || c > 0x7E) c = ' ';
        if (wrap && col >= kMaxPhysLine - 24 && c == ' ') {           // break at the first space past the soft limit
            if (o + 2 >= cap) return false;
            out[o++] = '\r'; out[o++] = '\n';
            col = 0; lineStart = true;
            continue;
        }
        if (wrap && col >= kMaxPhysLine) {                            // a word longer than the whole line: hard break
            if (o + 2 >= cap) return false;
            out[o++] = '\r'; out[o++] = '\n';
            col = 0; lineStart = true;
        }
        if (lineStart && (c == '#' || c == ';')) c = ' ';
        lineStart = false;
        if (o + 1 >= cap) return false;
        out[o++] = static_cast<char>(c);
        ++col;
    }
    return true;
}
inline bool PutRaw(char* out, size_t cap, size_t& o, const char* s)
{
    const size_t n = strlen(s);
    if (o + n >= cap) return false;
    memcpy(out + o, s, n); o += n; return true;
}
inline bool PutInt(char* out, size_t cap, size_t& o, int v)
{
    char d[12]; int k = 0; unsigned u = v < 0 ? 0u : static_cast<unsigned>(v);
    do { d[k++] = static_cast<char>('0' + u % 10); u /= 10; } while (u);
    while (k) { if (o + 1 >= cap) return false; out[o++] = d[--k]; }
    return true;
}
} // namespace detail

inline bool BuildLabelFile(const LabelSpec& s, char* out, size_t cap)
{
    using namespace detail;
    size_t o = 0;
    if (!s.label || !s.body || s.nReplies < 0 || s.nReplies > 5) return false;
    bool ok = PutRaw(out, cap, o, "; generated by uimod.dll (Longevity Mod) -- rewritten on demand, safe to delete\r\n\r\n#")
           && PutSan(out, cap, o, s.label, false) && PutRaw(out, cap, o, "\r\n#xs ") && PutInt(out, cap, o, s.xs)
           && PutRaw(out, cap, o, "\r\n");
    if (ok && s.caption) ok = PutRaw(out, cap, o, "#caption ") && PutSan(out, cap, o, s.caption, false) && PutRaw(out, cap, o, "\r\n");
    if (ok && s.sprite)  ok = PutRaw(out, cap, o, "#sprite ")  && PutSan(out, cap, o, s.sprite, false)  && PutRaw(out, cap, o, "\r\n");
    if (ok) ok = PutSan(out, cap, o, s.body, true, true) && PutRaw(out, cap, o, "\r\n\r\n");
    for (int i = 0; ok && i < s.nReplies; ++i)
        ok = s.replies[i] && s.replies[i][0] && PutSan(out, cap, o, s.replies[i], false) && PutRaw(out, cap, o, "\r\n");
    // No reply lines = the engine's own OK button (vanilla's message-only labels); the blank line
    // after the body then already ends the label.
    if (ok) ok = PutRaw(out, cap, o, s.nReplies ? "\r\n# ; This line must remain at end of file\r\n\r\n"
                                                : "# ; This line must remain at end of file\r\n\r\n");
    if (ok) out[o] = 0;
    return ok;
}

// ---- player-facing text (F2..F8 in the plan) -- ASCII, action always stated, WHAT is named ----
enum Context { kCtxMainMenu = 0, kCtxInGame = 1 };
enum PromptKind { kPromptUpdate = 0, kPromptPackStandalone = 1, kPromptPackQuitPending = 2 };
enum Action { kActNone = 0, kActQuitUpdate, kActSaveQuitUpdate, kActInstallToo, kActNotNow, kActNever };

struct ReplySet { const char* text[5]; Action act[5]; int n; };

inline void ReplySetFor(Context ctx, PromptKind kind, ReplySet* r)
{
    r->n = 0;
    auto add = [&](const char* t, Action a) { r->text[r->n] = t; r->act[r->n] = a; ++r->n; };
    // Reply 0 is the SAFE one: the engine returns the highlighted reply (0 unless the player moved)
    // on Esc, and vanilla puts the "no" first for that reason (REALLYQUIT: "Oops, no, wait!").
    const bool pack = kind != kPromptUpdate;
    if (kind == kPromptPackQuitPending) {              // the player already chose to update: add the pack to it?
        add("Not now (update without it)", kActNotNow);
        add("Yes, include it", kActInstallToo);
    } else if (ctx == kCtxInGame) {                    // the body says the game closes; the word pair is the save choice
        add("Not now", kActNotNow);
        add(pack ? "Save, then install" : "Save, then update", kActSaveQuitUpdate);
        add(pack ? "Install without saving" : "Update without saving", kActQuitUpdate);
    } else {
        add("Not now", kActNotNow);
        add(pack ? "Quit and install" : "Quit and update", kActQuitUpdate);
    }
    add("Don't ask me again", kActNever);
}

// Esc / a failed popup (-1) and any index outside the set read as "Not now".
inline Action ActionFor(const ReplySet& r, int reply)
{
    return reply >= 0 && reply < r.n ? r.act[reply] : kActNotNow;
}

// Index of the first reply with `act` in the set (-1 = none).
inline int ReplyIndexOf(const ReplySet& r, Action act)
{
    for (int i = 0; i < r.n; ++i) if (r.act[i] == act) return i;
    return -1;
}

constexpr char kCaption[]    = "Longevity Mod";
constexpr char kCoreLabel[]  = "Longevity Mod";
constexpr int  kPromptXs     = 460;      // REALLYQUIT is 320 with two short replies; the game's menus use 420. UNMEASURED in-game.

// The last paragraph of every offer: what "Don't ask me again" does -- the reply's label, one
// space, its meaning (user wording 2026-11-04, single space 2026-11-06; "Not now" is not
// explained). (Popup text is
// PARAGRAPHS: a '\n' only between paragraphs or list items, never inside a sentence -- the engine
// wraps to the box width, and a break we chose reads as a ragged line at any other width.)
// User rule 2026-10-31, still in force though the text no longer says it (user 2026-11-04):
// "a decline of any pack is reset when any new update releases for a module that is already
// installed." The DLL writes an UPDATE offer's decline at the offered version (`<item>:<ver>`)
// and a NEW pack's at `*` (`new:<id>:*`); install.py check_report applies the rule.
constexpr char kNeverUpdate[]  = "\"Don't ask me again\" Skips this update (undo in Preferences).";
constexpr char kNeverUpdates[] = "\"Don't ask me again\" Skips these updates (undo in Preferences).";
constexpr char kNeverPack[]    = "\"Don't ask me again\" Skips this pack (undo in Preferences).";

// The DeclinedUpdates version an item is declined at: the offered version for an update of
// something installed, kDeclineAny for a pack the player does not have. An update offer with
// no version (unreachable: the pipe parser refuses one) yields nullptr = write nothing; the
// failure path must never silence for good.
inline const char* DeclineVersionFor(bool newPack, const char* offered)
{
    if (newPack) return kDeclineAny;
    return offered && offered[0] ? offered : nullptr;
}

namespace detail {
inline bool Line(char* out, size_t cap, size_t& o, const char* a, const char* b = "", const char* c = "",
                 const char* d = "", const char* e = "", const char* f = "")
{
    const char* parts[] = { a, b, c, d, e, f };
    for (const char* p : parts) if (!PutRaw(out, cap, o, p)) return false;
    return PutRaw(out, cap, o, "\n");
}
} // namespace detail

// F2: the core and/or an installed pack is stale.
inline bool BuildUpdateBody(const UpdateInfo& u, Context ctx, char* out, size_t cap)
{
    using namespace detail;
    size_t o = 0;
    const int lines = (u.hasBase ? 1 : 0) + u.nStale;
    bool ok = Line(out, cap, o, lines > 1 ? "Updates are available:" : "An update is available:");
    if (ok && u.hasBase) ok = Line(out, cap, o, kCoreLabel, " ", u.baseFrom, " -> ", u.baseTo);
    for (int i = 0; ok && i < u.nStale; ++i) {
        char sz[24]; FormatBytes(u.stale[i].bytes, u.stale[i].hasBytes, sz, sizeof sz);
        ok = PutRaw(out, cap, o, u.stale[i].label) && PutRaw(out, cap, o, " ") && PutRaw(out, cap, o, u.stale[i].from)
          && PutRaw(out, cap, o, " -> ") && PutRaw(out, cap, o, u.stale[i].to);
        if (ok && sz[0]) ok = PutRaw(out, cap, o, " (") && PutRaw(out, cap, o, sz) && PutRaw(out, cap, o, ")");
        if (ok) ok = PutRaw(out, cap, o, "\n");
    }
    if (ok) ok = Line(out, cap, o, "");
    if (ok) ok = PutRaw(out, cap, o, "Updating closes the game and opens the updater in its own window. "
                                     "Your saved games are not affected.");
    if (ok && ctx == kCtxInGame)
        ok = PutRaw(out, cap, o, " If you update without saving, progress since your last save is lost.");
    if (ok) ok = PutRaw(out, cap, o, "\n\n");
    if (ok) ok = PutRaw(out, cap, o, lines > 1 ? kNeverUpdates : kNeverUpdate);
    if (ok) out[o] = 0;
    return ok;
}

// F3: a pack the player does not have. `alsoCoreTo` = the core version the updater will bring
// along (nullptr when the core is current or F2 already said so).
inline bool BuildPackBody(const Item& it, const char* alsoCoreTo, Context ctx, PromptKind kind, char* out, size_t cap)
{
    using namespace detail;
    size_t o = 0;
    char sz[24]; FormatBytes(it.bytes, it.hasBytes, sz, sizeof sz);
    bool ok;
    if (kind == kPromptPackQuitPending) {                  // the player already accepted an update
        ok = PutRaw(out, cap, o, "You chose to update. Add ") && PutRaw(out, cap, o, it.label);
        if (ok && sz[0]) ok = PutRaw(out, cap, o, " (") && PutRaw(out, cap, o, sz) && PutRaw(out, cap, o, ")");
        if (ok) ok = PutRaw(out, cap, o, " to that update? It is optional.");
    } else {
        ok = PutRaw(out, cap, o, it.label) && PutRaw(out, cap, o, " ") && PutRaw(out, cap, o, it.to)
          && PutRaw(out, cap, o, " is available. It is an optional");
        if (ok && sz[0]) ok = PutRaw(out, cap, o, " ") && PutRaw(out, cap, o, sz);
        if (ok) ok = PutRaw(out, cap, o, " download.");
        if (ok && alsoCoreTo) ok = PutRaw(out, cap, o, " Installing it also brings ") && PutRaw(out, cap, o, kCoreLabel)
                               && PutRaw(out, cap, o, " up to ") && PutRaw(out, cap, o, alsoCoreTo) && PutRaw(out, cap, o, " (required).");
        if (ok) ok = PutRaw(out, cap, o, "\n\nInstalling closes the game and opens the updater in its own window. "
                                         "Your saved games are not affected.");
        if (ok && ctx == kCtxInGame)
            ok = PutRaw(out, cap, o, " If you install without saving, progress since your last save is lost.");
    }
    if (ok) ok = PutRaw(out, cap, o, "\n\n") && PutRaw(out, cap, o, kNeverPack);
    if (ok) out[o] = 0;
    return ok;
}

// F6: manual install required (the kill switch). One compiled reason line per manifest reason.
// Paragraphs only (see kNeverUpdate). The address sits on a line of its own on purpose.
#define LVUPD_MANUAL_HEAD "Longevity Mod can no longer update itself. "
#define LVUPD_MANUAL_TAIL " Your game and saved games are fine.\n\n" \
    "To keep getting updates, download and run the new installer. Type this address into your web browser:\n" \
    "longevitymods.com/vaccine/download"
inline const char* ManualNoticeBody(int reason)
{
    switch (reason) {
    case kReasonBootstrapDefect: return LVUPD_MANUAL_HEAD "This version's updater has a fault." LVUPD_MANUAL_TAIL;
    case kReasonBaseUnsupported: return LVUPD_MANUAL_HEAD "This version is no longer supported." LVUPD_MANUAL_TAIL;
    case kReasonTooOld:          return LVUPD_MANUAL_HEAD "Your version is too old to update on its own." LVUPD_MANUAL_TAIL;
    case kReasonProtocol:        return LVUPD_MANUAL_HEAD "This release needs a newer installer." LVUPD_MANUAL_TAIL;
    default:                     return "Longevity Mod can no longer update itself." LVUPD_MANUAL_TAIL;
    }
}
#undef LVUPD_MANUAL_HEAD
#undef LVUPD_MANUAL_TAIL

// F7: the player said yes but the updater could not be started.
constexpr char kNoInstallerBody[] =
    "The updater could not be started, so nothing was installed. Your game continues.\n\n"
    "To update, download the installer from longevitymods.com/vaccine/download (type it into your web browser).";

// F8: the updater is running but the game could not close itself.
constexpr char kQuitManuallyBody[] =
    "The update is ready, but the game could not close itself. "
    "Please quit the game within 90 seconds (Game menu > Quit, or Esc at the main menu). "
    "The update starts as soon as the game has closed. "
    "If you miss this, the update is offered again the next time you start the game.";

// In-game "Save, then ...": the save dialog was cancelled or failed.
constexpr char kSaveCancelledBody[] =
    "The update was not started because the game was not saved. "
    "You will be asked again the next time you start the game.";

// Preferences: "Reset Skipped Updates" confirmation.
constexpr char kSubscribeBody[] =
    "Show all update reminders again?\n\n"
    "This undoes every \"Don't ask me again\" and \"Don't show this again\" you chose for Longevity Mod "
    "and its optional packs, and turns on Check for Updates at Startup.\n\n"
    "The game checks for updates when it starts, so restart the game to check now.";

} // namespace lvupd
