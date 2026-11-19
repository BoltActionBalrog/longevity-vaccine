// Self-test harness for thinkerlive.h (tests\test_thinker_live.py builds and runs it once per module): the readers
// of memory and files the startup check does not own, run against REAL pages and REAL files.
//   t.exe <scratch dir>
// Prints one "PASS <name>" or "FAIL <name> <detail>" line per check.
#include <cstdio>
#include <string>

#include "../../src/uimod/src/thinkerlive.h"

namespace {

using namespace thinkerlive;
using thinkercheck::LabelKind;

void Check(const char* name, bool ok, const std::string& detail = "")
{
    std::printf("%s %s %s\n", ok ? "PASS" : "FAIL", name, ok ? "" : detail.c_str());
}

std::wstring Path(const std::wstring& dir, const wchar_t* name) { return dir + L"\\" + name; }

bool WriteFileBytes(const std::wstring& path, const std::string& bytes)
{
    const HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD put = 0;
    const BOOL ok = WriteFile(h, bytes.data(), static_cast<DWORD>(bytes.size()), &put, nullptr);
    CloseHandle(h);
    return ok && put == bytes.size();
}

// ---- ReadLabel over real pages: one committed page followed by one that is only reserved -------------------------
void Memory()
{
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    const size_t page = si.dwPageSize;
    char* base = static_cast<char*>(VirtualAlloc(nullptr, 2 * page, MEM_RESERVE, PAGE_NOACCESS));
    if (!base || !VirtualAlloc(base, page, MEM_COMMIT, PAGE_READWRITE)) { Check("pages", false, "VirtualAlloc"); return; }
    const uintptr_t lo = reinterpret_cast<uintptr_t>(base), hi = lo + 2 * page;
    memset(base, 'x', page);

    const char label[] = "Thinker Mod v5.6";
    const size_t n = sizeof label;                              // with the terminator
    const char* why = nullptr;

    memcpy(base + 100, label, n);
    Label l = ReadLabel(base + 100, lo, hi, &why);
    Check("a_label_inside_the_image", l.kind == LabelKind::Version && strcmp(l.version, "5.6") == 0 && !why);

    // the string ends exactly at the end of the committed page: its terminator is the page's last byte
    memcpy(base + page - n, label, n);
    l = ReadLabel(base + page - n, lo, hi, &why);
    Check("a_label_ending_on_the_last_readable_byte", l.kind == LabelKind::Version && !why);

    // the same string one byte later: its terminator would be the first byte of the reserved page. The read must
    // stop at the region's end -- reaching for that byte is an access violation -- and report "no terminator".
    memset(base + page - n, 'x', n);
    memcpy(base + page - (n - 1), label, n - 1);
    l = ReadLabel(base + page - (n - 1), lo, hi, &why);
    Check("a_string_running_off_the_readable_region", l.kind == LabelKind::Unrecognised && why && strstr(why, "terminator"));

    l = ReadLabel(base + page + 16, lo, hi, &why);              // into the reserved page
    Check("a_pointer_into_unreadable_memory", l.kind == LabelKind::Unrecognised && why && strstr(why, "readable"));

    l = ReadLabel(label, lo, hi, &why);                         // a perfectly good string, but not inside the image
    Check("a_pointer_outside_the_image", l.kind == LabelKind::Unrecognised && why && strstr(why, "inside"));
    l = ReadLabel(nullptr, lo, hi, &why);
    Check("a_null_pointer", l.kind == LabelKind::Unrecognised && why != nullptr);

    // the image ends inside the committed page, before the terminator: the image's end bounds the read too
    memcpy(base + 200, label, n);
    l = ReadLabel(base + 200, lo, lo + 200 + n - 1, &why);
    Check("a_string_running_off_the_image", l.kind == LabelKind::Unrecognised && why && strstr(why, "terminator"));
    l = ReadLabel(base + 200, lo, lo + 200 + n, &why);
    Check("a_string_ending_on_the_images_last_byte", l.kind == LabelKind::Version && !why);

    // 64 bytes is the most that is ever read: a longer run without a terminator is not a label
    memset(base + 400, 'A', 200);
    l = ReadLabel(base + 400, lo, hi, &why);
    Check("a_long_unterminated_run", l.kind == LabelKind::Unrecognised && why && strstr(why, "terminator"));

    memcpy(base + 700, "RELEASE 2.0", 12);
    l = ReadLabel(base + 700, lo, hi, &why);
    Check("a_readable_string_that_is_not_a_label", l.kind == LabelKind::Unrecognised && why && strstr(why, "not a Thinker"));

    Check("readable_inside_one_region", Readable(base, page) && Readable(base + page - 1, 1));
    Check("not_readable_across_into_reserved", !Readable(base + page - 1, 2) && !Readable(base + page, 1) && !Readable(nullptr, 1));
    VirtualFree(base, 0, MEM_RELEASE);
}

// ---- files ---------------------------------------------------------------------------------------------------------
void Files(const std::wstring& dir)
{
    const std::wstring v = Path(dir, L"VERSION");
    struct Case { const char* name; std::string bytes; const char* want; };
    const Case cases[] = {
        { "version_plain", "1.2.0\n", "1.2.0" },
        { "version_crlf", "1.2.0\r\n", "1.2.0" },
        { "version_no_newline", "1.2.0", "1.2.0" },
        { "version_bom", "\xEF\xBB\xBF" "1.2.0\n", "1.2.0" },
        { "version_trailing_space", "1.2.0 \t\r\n", "1.2.0" },
        { "version_empty", "", "" },
        { "version_two_lines_is_not_a_version", "1.2.0\nmore\n", "1.2.0\nmore" },
    };
    for (const Case& c : cases) {
        WriteFileBytes(v, c.bytes);
        const std::string got = ReadVersionFile(v.c_str());
        Check(c.name, got == c.want, got);
    }
    WriteFileBytes(v, std::string(500, '9'));
    Check("version_long_content_is_cut_and_refused", ReadVersionFile(v.c_str()).size() == 40 &&
                                                     thinkercheck::VersionOlder(ReadVersionFile(v.c_str()).c_str(), "1.0.0"));
    Check("version_missing_file_is_empty_and_older", ReadVersionFile(Path(dir, L"nope").c_str()).empty() &&
                                                     thinkercheck::VersionOlder("", "1.0.0"));
    WriteFileBytes(v, "1.2.0\nmore\n");
    Check("version_with_a_second_line_is_refused", thinkercheck::VersionOlder(ReadVersionFile(v.c_str()).c_str(), "1.0.0"));

    // FileMentions: the capability scan of the resident install.py
    const std::wstring py = Path(dir, L"install.py");
    WriteFileBytes(py, "import argparse\np.add_argument(\"--fix-thinker\", action=\"store_true\")\n");
    Check("mentions_a_present_token", FileMentions(py.c_str(), "--fix-thinker"));
    WriteFileBytes(py, "import argparse\np.add_argument(\"--update\")\n# --fix-thinke\n");
    Check("does_not_mention_an_absent_token", !FileMentions(py.c_str(), "--fix-thinker"));
    std::string big(64 * 1024 - 5, '#');                        // the token straddles the 64 KB read boundary
    big += "--fix-thinker";
    big += std::string(1000, '\n');
    WriteFileBytes(py, big);
    Check("mentions_a_token_across_a_read_boundary", FileMentions(py.c_str(), "--fix-thinker"));
    std::string atEnd(200 * 1024, 'x');                         // (`far` is a windows.h macro)
    atEnd += "--fix-thinker";
    WriteFileBytes(py, atEnd);
    Check("mentions_a_token_at_the_very_end_of_a_large_file", FileMentions(py.c_str(), "--fix-thinker"));
    Check("a_missing_file_mentions_nothing", !FileMentions(Path(dir, L"nope.py").c_str(), "--fix-thinker"));

    // LabelFromFile: the installer's rule -- every label string in the file must agree
    const std::wstring dll = Path(dir, L"thinker.dll");
    auto z = [](const char* s) { return std::string(s) + '\0'; };
    bool read = false;
    WriteFileBytes(dll, std::string(300, '\x01') + z("Thinker Mod v5.5") + std::string(50, '\x02') + z("Thinker Mod v5.5") +
                        z("junk") + z("Thinker Mod v5.5") + z("Thinker Mod v5.5"));
    Label l = LabelFromFile(dll.c_str(), &read);
    Check("file_four_identical_labels", read && l.kind == LabelKind::Version && strcmp(l.version, "5.5") == 0);
    WriteFileBytes(dll, z("xx") + z("Thinker Mod develop build") + z("Thinker Mod develop build"));
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_development_build", read && l.kind == LabelKind::Develop);
    WriteFileBytes(dll, z("Thinker Mod v5.5") + z("Thinker Mod v5.6"));
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_two_different_labels_is_unrecognised", read && l.kind == LabelKind::Unrecognised);
    WriteFileBytes(dll, z("Thinker Mod v5.5") + z("Thinker Mod develop build"));
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_a_version_and_a_development_label_is_unrecognised", read && l.kind == LabelKind::Unrecognised);
    WriteFileBytes(dll, z("Thinker Mod requires this") + z("Thinker Mod v5.5") + z("Thinker Mod: a note"));
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_other_text_after_the_name_is_ignored", read && l.kind == LabelKind::Version && strcmp(l.version, "5.5") == 0);
    WriteFileBytes(dll, std::string("Thinker Mod v5.5"));       // no terminator at the end of the file
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_an_unterminated_label_is_not_one", read && l.kind == LabelKind::Unrecognised);
    WriteFileBytes(dll, z("Thinker Mod v5.5") + "Thinker Mod v5.6" + std::string(60, 'y') + '\0');
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_a_string_longer_than_a_label_is_ignored", read && l.kind == LabelKind::Version && strcmp(l.version, "5.5") == 0);
    WriteFileBytes(dll, std::string(4096, '\0'));
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_without_any_label", read && l.kind == LabelKind::Unrecognised);
    l = LabelFromFile(Path(dir, L"none.dll").c_str(), &read);
    Check("file_missing_is_not_read", !read && l.kind == LabelKind::Unrecognised);
    WriteFileBytes(dll, "");
    l = LabelFromFile(dll.c_str(), &read);
    Check("file_empty_is_not_read", !read);
}

void Text()
{
    // a path the ANSI code page cannot hold must still reach the log
    const wchar_t path[] = { L'C', L':', L'\\', 0x0418, 0x0433, 0x0440, 0x044B, L'\\', L'S', L'M', L'A', L'C', 0 };
    const std::string u = Utf8(path);
    Check("utf8_keeps_a_non_ansi_path", u == "C:\\\xD0\x98\xD0\xB3\xD1\x80\xD1\x8B\\SMAC", u);
    Check("utf8_of_nothing_is_empty", Utf8(nullptr).empty() && Utf8(L"").empty());
}

} // namespace

int wmain(int argc, wchar_t** argv)
{
    if (argc != 2) return 2;
    Memory();
    Files(argv[1]);
    Text();
    return 0;
}
